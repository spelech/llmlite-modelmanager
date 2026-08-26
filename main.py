from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import os
import json
import yaml
import time
import asyncio
import httpx
from google import genai
from google.oauth2 import service_account
from typing import List, Dict, Optional
from contextlib import asynccontextmanager

from app.database import (
    init_db,
    get_all_settings,
    set_setting,
    get_setting,
    get_all_discovered_models,
    get_unhealthy_models
)
from app.notifications import send_notification
from app.discovery import classify_model_tier, process_and_track_discovered_models
from app.health import probe_model, check_active_models_health
from app.mcp_server import mcp, set_app_state_ref

# --- Default Paths & Keys (Internal Fallbacks) ---
DEFAULT_CONFIG_PATH = "/app/config/config.yaml"
DEFAULT_VERTEX_CREDS = "/app/vertex_credentials.json"
PROXY_URL = "http://litellm:4000/v1/chat/completions"

CACHE_FILE = "/app/config/verified_models_cache.json"
CACHE_EXPIRY_DAYS = 7
DEFAULT_LOCATION = "global"

# App Versioning
if os.path.exists("VERSION"):
    with open("VERSION", "r") as f:
        APP_VERSION = f.read().strip()
else:
    APP_VERSION = "dev"
APP_BUILD_TIME = os.environ.get("APP_BUILD_TIME", "unknown")

# Global App State
app_state = {
    "or_models": [],
    "vx_models": [],
    "last_verification_time": 0,
    "settings": {}  # Loaded from DB on startup
}

set_app_state_ref(app_state)

def get_app_setting(key: str, default=None):
    """Helper to get setting from app_state or environment."""
    return app_state["settings"].get(key) or os.environ.get(key) or default

async def refresh_app_settings():
    """Load settings from DB into memory."""
    app_state["settings"] = await get_all_settings()

templates = Jinja2Templates(directory="app/templates")

# Fallback pricing table for 2026 Gemini models
FALLBACK_PRICING = {
    "gemini-3.5-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-3.5-pro": {"prompt_1m": 1.25, "completion_1m": 3.75},
    "gemini-3.1-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-3.1-flash-lite": {"prompt_1m": 0.03, "completion_1m": 0.10},
    "gemini-3.1-pro": {"prompt_1m": 1.25, "completion_1m": 3.75},
    "gemini-3-pro": {"prompt_1m": 1.25, "completion_1m": 3.75},
    "gemini-3-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-2.5-flash": {"prompt_1m": 0.10, "completion_1m": 0.40},
    "gemini-2.5-pro": {"prompt_1m": 1.25, "completion_1m": 3.75},
    "gemini-2.0-flash": {"prompt_1m": 0.10, "completion_1m": 0.40},
    "gemini-embedding": {"prompt_1m": 0.02, "completion_1m": 0.0},
}

GEMINI_SPECS = {
    "gemini-2.5-pro": {"ctx": 2000000, "out": 8192},
    "gemini-2.5-flash": {"ctx": 1000000, "out": 8192},
    "gemini-3.5-flash": {"ctx": 1000000, "out": 8192},
    "gemini-3.1-flash-lite": {"ctx": 1000000, "out": 8192},
    "gemini-3.1-pro": {"ctx": 2000000, "out": 8192},
}

def extract_capabilities(description: str, model_id: str) -> Dict[str, bool]:
    """Heuristic capability extraction for input/output modalities and features."""
    desc_low = description.lower()
    mid_low = model_id.lower()
    
    def match(keywords):
        return any(k in desc_low or k in mid_low for k in keywords)

    return {
        "text_in": True,
        "text_out": True,
        "image_in": match(["vision", "image", "multimodal", "flash", "pro"]),
        "image_out": match(["dall-e", "imagen", "generator", "draw"]),
        "audio_in": match(["audio", "speech", "whisper"]),
        "audio_out": match(["tts", "text-to-speech", "audio"]),
        "video_in": match(["video", "multimodal"]),
        "video_out": match(["video-gen", "sora"]),
        "function_calling": match(["function", "tool", "agent"]),
        "streaming": True
    }

async def get_openrouter_models() -> List[Dict]:
    """Fetch and format OpenRouter models with capabilities and tiers."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://openrouter.ai/api/v1/models?sort=most-popular")
            if resp.status_code != 200:
                return []
            
            models = []
            for idx, m in enumerate(resp.json().get("data", [])):
                brand = m['id'].split("/")[0] if "/" in m['id'] else "other"
                pricing_dict = {
                    "prompt": float(m.get("pricing", {}).get("prompt", 0)),
                    "completion": float(m.get("pricing", {}).get("completion", 0)),
                    "prompt_1m": float(m.get("pricing", {}).get("prompt", 0)) * 1_000_000,
                    "completion_1m": float(m.get("pricing", {}).get("completion", 0)) * 1_000_000
                }
                model_item = {
                    "id": f"openrouter/{m['id']}",
                    "name": m["name"],
                    "brand": brand,
                    "popularity": idx,
                    "pricing": pricing_dict,
                    "max_input_tokens": m.get("context_length", 0),
                    "max_output_tokens": m.get("top_provider", {}).get("max_completion_tokens", 0),
                    "capabilities": extract_capabilities(m.get("description", ""), m["id"])
                }
                model_item["tier"] = classify_model_tier(model_item)
                models.append(model_item)
            return models
    except Exception as e:
        print(f"Error fetching OpenRouter: {e}")
        return []

def get_google_access_token():
    """Generate a Google access token using service account."""
    try:
        from google.auth.transport.requests import Request as AuthRequest
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
        creds = service_account.Credentials.from_service_account_file(
            get_app_setting("VERTEX_CREDENTIALS_PATH", DEFAULT_VERTEX_CREDS), scopes=scopes)
        creds.refresh(AuthRequest())
        return creds.token
    except Exception as e:
        print(f"Error getting Google token: {e}")
        return None

async def fetch_vertex_model_metadata(model_id: str) -> Dict[str, int]:
    """Fetch technical limits (tokens) for a canonical model ID."""
    token = get_google_access_token()
    if not token:
        return {}
    
    url = f"https://aiplatform.googleapis.com/v1/projects/{get_app_setting('VERTEX_PROJECT')}/locations/{get_app_setting('VERTEX_LOCATION', 'global')}/publishers/google/models/{model_id}"
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "max_input_tokens": int(data.get("inputTokenLimit", 0)),
                    "max_output_tokens": int(data.get("outputTokenLimit", 0))
                }
        except Exception as e:
            print(f"Exception in fetch_vertex_model_metadata for {model_id}: {e}")
    return {}

async def fetch_vertex_billing_skus() -> Dict[str, Dict]:
    """Fetch pricing data for Gemini models from the Billing API."""
    token = get_google_access_token()
    if not token:
        return {}

    try:
        url = "https://cloudbilling.googleapis.com/v1/services/C7E2-9256-1C43/skus"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return {}
            
            skus = resp.json().get("skus", [])
            pricing_map = {}
            
            for s in skus:
                desc = s.get("description", "")
                if "Gemini" not in desc:
                    continue
                if any(x in desc for x in ["High Priority", "Provisioned", "Commitment", "Reserved"]):
                    continue

                name_parts = desc.split(" - ")[0].split(" GA ")[0].strip()
                model_key = name_parts.lower().replace(" ", "-")
                
                if model_key not in pricing_map:
                    pricing_map[model_key] = {"prompt_1m": 0.0, "completion_1m": 0.0}
                
                pricing_info = s.get("pricingInfo", [{}])[0].get("pricingExpression", {})
                rate = pricing_info.get("tieredRates", [{}])[0].get("unitPrice", {})
                price_usd = float(rate.get("units", 0)) + (float(rate.get("nanos", 0)) / 1e9)
                
                if "Input" in desc:
                    pricing_map[model_key]["prompt_1m"] = price_usd * 1_000_000
                elif "Output" in desc:
                    pricing_map[model_key]["completion_1m"] = price_usd * 1_000_000
            
            return pricing_map
    except Exception as e:
        print(f"Error fetching Vertex SKUs: {e}")
        return {}

async def fetch_vertex_publisher_models() -> List[str]:
    """List all available foundation models in the region using GenAI SDK."""
    try:
        from google import genai
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
        creds = service_account.Credentials.from_service_account_file(
            get_app_setting("VERTEX_CREDENTIALS_PATH", DEFAULT_VERTEX_CREDS), scopes=scopes)
        client = genai.Client(
            vertexai=True,
            project=get_app_setting("VERTEX_PROJECT"),
            location=get_app_setting("VERTEX_LOCATION", 'global'),
            credentials=creds
        )
        
        ids = []
        for model in client.models.list():
            mid = model.name.split("/")[-1]
            if "gemini" in mid.lower():
                ids.append(mid)
        return list(set(ids))
    except Exception as e:
        print(f"SDK Discovery Error: {e}")
        return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp", "gemini-2.5-pro", "gemini-2.5-flash"]

async def verify_and_cache_vertex_models():
    """Discover and merge model data using SDK and Billing API."""
    print(f"Starting Vertex discovery for {get_app_setting('VERTEX_LOCATION', 'global')} (Universal Mode)...")
    
    model_ids = await fetch_vertex_publisher_models()
    pricing_map = await fetch_vertex_billing_skus()
    
    models = []
    for mid in model_ids:
        p_data = {"prompt_1m": 0.0, "completion_1m": 0.0}
        
        base_3 = "-".join(mid.split("-")[:3])
        base_2 = "-".join(mid.split("-")[:2])
        
        search_keys = [
            mid, f"{mid}-text-input", f"{mid}-global-text-input", f"{mid}-input",
            base_3, f"{base_3}-text-input", f"{base_3}-global-text-input", f"{base_3}-input",
            base_2, f"{base_2}-text-input", f"{base_2}-input"
        ]
                       
        for sk in search_keys:
            if sk in pricing_map and pricing_map[sk]["prompt_1m"] > 0:
                p_data["prompt_1m"] = pricing_map[sk]["prompt_1m"]
                break
        
        search_keys_out = [
            f"{mid}-text-output", f"{mid}-global-text-output", f"{mid}-output",
            f"{base_3}-text-output", f"{base_3}-global-text-output", f"{base_3}-output",
            f"{base_2}-text-output", f"{base_2}-output"
        ]
                           
        for sk in search_keys_out:
            if sk in pricing_map and pricing_map[sk]["completion_1m"] > 0:
                p_data["completion_1m"] = pricing_map[sk]["completion_1m"]
                break
        
        if p_data["prompt_1m"] == 0 or p_data["completion_1m"] == 0:
            for b in [mid, base_3, base_2]:
                if b in FALLBACK_PRICING:
                    if p_data["prompt_1m"] == 0:
                        p_data["prompt_1m"] = FALLBACK_PRICING[b]["prompt_1m"]
                    if p_data["completion_1m"] == 0:
                        p_data["completion_1m"] = FALLBACK_PRICING[b]["completion_1m"]
                    break

        spec = GEMINI_SPECS.get(mid, {"ctx": 1000000, "out": 8192})
        if mid not in GEMINI_SPECS:
            base_id = "-".join(mid.split("-")[:3])
            spec = GEMINI_SPECS.get(base_id, spec)

        model_item = {
            "id": f"vertex_ai/{mid}",
            "name": mid.replace("-", " ").title(),
            "brand": "google",
            "pricing": {
                "prompt": p_data["prompt_1m"] / 1_000_000,
                "completion": p_data["completion_1m"] / 1_000_000,
                "prompt_1m": p_data["prompt_1m"],
                "completion_1m": p_data["completion_1m"]
            },
            "max_input_tokens": spec["ctx"],
            "max_output_tokens": spec["out"],
            "capabilities": extract_capabilities("", mid)
        }
        model_item["tier"] = classify_model_tier(model_item)
        models.append(model_item)

    verified_models = sorted(models, key=lambda x: x["name"])
    app_state["vx_models"] = verified_models
    app_state["last_verification_time"] = time.time()
    
    with open(CACHE_FILE, "w") as f:
        json.dump({"timestamp": app_state["last_verification_time"], "models": verified_models}, f)
        
    print(f"Vertex discovery finished. Found {len(verified_models)} models.")
    
    # Track discovered models and notify if trending
    await process_and_track_discovered_models(app_state["or_models"] + verified_models, notify=True)
    
    try:
        config_path = get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH)
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                cfg = yaml.safe_load(f) or {}
            export_opencode_config(cfg.get("model_list", []))
    except Exception as e:
        print(f"Error exporting opencode config during model verification: {e}")

def update_vertex_creds_file():
    """Write Vertex JSON from settings to file for GCP SDK use."""
    json_content = get_app_setting("VERTEX_CREDENTIALS_JSON")
    if json_content:
        try:
            json.loads(json_content)
            with open(DEFAULT_VERTEX_CREDS, "w") as f:
                f.write(json_content)
            print(f"Updated Vertex credentials file at {DEFAULT_VERTEX_CREDS}")
        except Exception as e:
            print(f"Error writing Vertex credentials JSON: {e}")

async def initial_load_models():
    """Load OpenRouter and check cache for Vertex on startup."""
    app_state["or_models"] = await get_openrouter_models()
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                cache_data = json.load(f)
                if time.time() - cache_data.get("timestamp", 0) < (CACHE_EXPIRY_DAYS * 24 * 3600):
                    models = cache_data.get("models", [])
                    for m in models:
                        if "capabilities" not in m:
                            m["capabilities"] = extract_capabilities("", m["id"])
                        if "tier" not in m:
                            m["tier"] = classify_model_tier(m)
                    app_state["vx_models"] = models
                    app_state["last_verification_time"] = cache_data.get("timestamp", 0)
                    await process_and_track_discovered_models(app_state["or_models"] + models, notify=False)
                    return
    except Exception as e:
        print(f"Cache load error: {e}")
        
    asyncio.create_task(verify_and_cache_vertex_models())

async def periodic_health_monitor():
    """Periodic background loop checking active model health and alerting outages once a day."""
    while True:
        try:
            interval_hours = float(await get_setting("HEALTH_CHECK_INTERVAL_HOURS", "24"))
            await asyncio.sleep(max(300, interval_hours * 3600))
            print("Running periodic model health check (0 tokens / catalog mode)...")
            config_path = get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH)
            probe_mode = await get_setting("PROBE_MODE", "catalog")
            await check_active_models_health(config_path=config_path, notify=True, mode=probe_mode)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error in periodic health monitor: {e}")
            await asyncio.sleep(600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await refresh_app_settings()
    update_vertex_creds_file()
    await initial_load_models()
    
    # Start periodic health monitor
    monitor_task = asyncio.create_task(periodic_health_monitor())
    yield
    monitor_task.cancel()

app = FastAPI(title="LiteLLM Manager", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount FastMCP endpoints for 2026-07-28 Streamable HTTP and SSE protocols
app.mount("/mcp", mcp.http_app(transport="http"))
app.mount("/sse", mcp.http_app(transport="sse"))

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={
            "or_models": app_state["or_models"], 
            "vx_models": app_state["vx_models"],
            "version": APP_VERSION,
            "build_time": APP_BUILD_TIME
        }
    )

@app.post("/test")
async def test_model_endpoint(model_id: str = Form(...)):
    """Test model availability directly via provider APIs (1-token live probe)."""
    res = await probe_model(model_id, app_state["settings"], mode="live")
    if res["healthy"]:
        return {"status": "success", "response": res.get("response", "OK"), "latency_ms": res.get("latency_ms")}
    return {"status": "error", "message": res.get("error", "Unknown error")}

@app.post("/force-refresh")
async def force_refresh():
    if os.path.exists(CACHE_FILE):
        try:
            os.remove(CACHE_FILE)
        except:
            pass
    app_state["or_models"] = await get_openrouter_models()
    await verify_and_cache_vertex_models()
    return {"status": "success"}

@app.post("/restart-litellm")
async def restart_litellm_endpoint():
    try:
        import docker
        client = docker.from_env()
        client.containers.get("litellm").restart()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/settings")
async def api_get_settings():
    return await get_all_settings()

@app.post("/api/settings")
async def api_update_settings(data: Dict[str, str]):
    for k, v in data.items():
        await set_setting(k, v)
    await refresh_app_settings()
    update_vertex_creds_file()
    return {"status": "success"}

@app.get("/api/config")
async def get_config():
    try:
        with open(get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH), "r") as f:
            config = yaml.safe_load(f) or {}
            model_list = config.get("model_list", [])
            selected_ids = [
                m.get("litellm_params", {}).get("model")
                for m in model_list
                if m.get("litellm_params", {}).get("model")
            ]
            return {"selected_ids": selected_ids}
    except Exception as e:
        return {"error": str(e)}

def export_opencode_config(models: list, target_path: str = "/app/opencode_config/opencode.jsonc"):
    """Sync active LiteLLM models to OpenCode configuration file."""
    if not os.path.exists(target_path):
        return
    
    try:
        with open(target_path, "r") as f:
            content = json.load(f)
    except Exception as e:
        print(f"Error reading opencode config: {e}")
        return

    if "provider" not in content:
        content["provider"] = {}
    if "litellm" not in content["provider"]:
        content["provider"]["litellm"] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "LiteLLM Gateway",
            "options": {"baseURL": "http://10.0.0.10:8448/v1"},
            "models": {}
        }
    
    opencode_models = {}
    for m in models:
        m_name = m.get("model_name")
        if not m_name or m_name.endswith("*"):
            continue
        
        info = m.get("model_info", {})
        ctx_limit = info.get("max_input_tokens", 128000) or 128000
        out_limit = info.get("max_output_tokens", 8192) or 8192
        
        opencode_models[m_name] = {
            "name": m_name,
            "limit": {
                "context": ctx_limit,
                "output": out_limit
            }
        }
    
    content["provider"]["litellm"]["models"] = opencode_models
    
    with open(target_path, "w") as f:
        json.dump(content, f, indent=2)

@app.post("/api/sync/opencode")
async def sync_opencode():
    config_path = get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH)
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f) or {}
            models = config.get("model_list", [])
            export_opencode_config(models)
            return {"status": "success", "exported_models": len(models)}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Config file not found"}

async def sync_models_internal(selected_ids: List[str]) -> Dict[str, any]:
    """Core logic to sync selected models into LiteLLM config and OpenCode config."""
    all_models = app_state["or_models"] + app_state["vx_models"]
    model_map = {m["id"]: m for m in all_models}
    
    config_path = get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH)
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
    
    new_model_list = []
    for mid in selected_ids:
        m_data = model_map.get(mid, {})
        pricing = m_data.get("pricing", {})
        
        entry = {
            "model_name": mid.split("/")[-1],
            "litellm_params": {"model": mid},
            "model_info": {
                "id": mid,
                "input_cost_per_token": pricing.get("prompt", 0),
                "output_cost_per_token": pricing.get("completion", 0),
                "max_input_tokens": m_data.get("max_input_tokens", 0),
                "max_output_tokens": m_data.get("max_output_tokens", 0),
                "capabilities": m_data.get("capabilities", {}),
                "brand": m_data.get("brand", "other")
            }
        }
        
        if mid.startswith("openrouter/"):
            entry["litellm_params"]["api_key"] = get_app_setting("OPENROUTER_API_KEY")
        elif mid.startswith("vertex_ai/"):
            entry["litellm_params"].update({
                "vertex_project": get_app_setting("VERTEX_PROJECT"),
                "vertex_location": get_app_setting("VERTEX_LOCATION", "global"),
                "vertex_credentials": "/app/vertex_credentials.json"
            })
            entry["model_info"]["input_cost_per_character"] = pricing.get("prompt", 0)
            entry["model_info"]["output_cost_per_character"] = pricing.get("completion", 0)
            
        new_model_list.append(entry)
    
    existing_list = config.get("model_list", [])
    wildcards = [m for m in existing_list if "*" in m.get("model_name", "")]
    
    config["model_list"] = new_model_list + wildcards
    
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
        
    export_opencode_config(config["model_list"])
    return {"status": "success", "updated_models": len(new_model_list)}

@app.post("/sync")
async def sync_models_endpoint(request: Request):
    form_data = await request.form()
    selected_ids = form_data.getlist("models")
    return await sync_models_internal(selected_ids)

@app.get("/api/models")
async def api_models():
    return {"openrouter": app_state["or_models"], "vertex": app_state["vx_models"]}

@app.get("/api/models/discovered")
async def api_discovered_models():
    models = await get_all_discovered_models()
    return [{"id": m.id, "name": m.name, "tier": m.tier, "provider": m.provider, "is_healthy": m.is_healthy, "last_error": m.last_error} for m in models]

@app.post("/api/health/check")
async def api_health_check(payload: Optional[Dict[str, str]] = None):
    mode = payload.get("mode") if payload else None
    config_path = get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH)
    return await check_active_models_health(config_path=config_path, notify=True, mode=mode)

@app.post("/api/notifications/test")
async def api_test_notification(payload: Optional[Dict[str, str]] = None):
    url = payload.get("url") if payload else None
    return await send_notification(
        title="LiteLLM Manager Test Notification",
        body="Apprise / Ntfy connectivity test is successful from LiteLLM Manager.",
        notification_type="info",
        tags="test,robot",
        override_url=url
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
