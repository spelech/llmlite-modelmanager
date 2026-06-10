from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import json
import yaml
import time
import asyncio
import httpx
from google.oauth2 import service_account
from typing import List, Dict
from contextlib import asynccontextmanager

# --- Config Paths ---
CONFIG_PATH = os.environ.get("LITELLM_CONFIG", "/app/config/config.yaml")
VERTEX_CREDENTIALS = os.environ.get("VERTEX_CREDENTIALS_PATH", "/app/vertex_credentials.json")
PROXY_URL = "http://litellm:4000/v1/chat/completions"
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-local-wileyriley-gateway-12345")
CACHE_FILE = "/app/config/verified_models_cache.json"
CACHE_EXPIRY_DAYS = 7
# App Versioning
if os.path.exists("VERSION"):
    with open("VERSION", "r") as f:
        APP_VERSION = f.read().strip()
else:
    APP_VERSION = os.environ.get("APP_VERSION", "dev")
APP_BUILD_TIME = os.environ.get("APP_BUILD_TIME", "unknown")

# Vertex defaults
DEFAULT_PROJECT = os.environ.get("VERTEX_PROJECT")
DEFAULT_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")

# Global App State for caching model lists in memory
app_state = {
    "or_models": [],
    "vx_models": [],
    "last_verification_time": 0
}

templates = Jinja2Templates(directory="app/templates")

# Fallback pricing table for 2026 Gemini models
FALLBACK_PRICING = {
    "gemini-3.5-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-3.5-pro": {"prompt_1m": 3.50, "completion_1m": 10.50},
    "gemini-3.1-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-3.1-flash-lite": {"prompt_1m": 0.03, "completion_1m": 0.10},
    "gemini-2.5-flash": {"prompt_1m": 0.10, "completion_1m": 0.40},
    "gemini-2.5-flash-lite": {"prompt_1m": 0.05, "completion_1m": 0.20},
    "gemini-2.5-pro": {"prompt_1m": 3.50, "completion_1m": 10.50},
    "gemini-1.5-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-1.5-pro": {"prompt_1m": 3.50, "completion_1m": 10.50},
}

def extract_capabilities(description: str, model_id: str) -> Dict[str, bool]:
    """Heuristic capability extraction for input/output modalities and features."""
    desc_low = description.lower()
    mid_low = model_id.lower()
    
    # Heuristic helpers
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
        "streaming": True # Generally assumed supported
    }

async def get_openrouter_models() -> List[Dict]:
    """Fetch and format OpenRouter models with capabilities."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://openrouter.ai/api/v1/models")
            if resp.status_code != 200:
                return []
            
            models = []
            for m in resp.json().get("data", []):
                brand = m['id'].split("/")[0] if "/" in m['id'] else "other"
                models.append({
                    "id": f"openrouter/{m['id']}",
                    "name": m["name"],
                    "brand": brand,
                    "pricing": {
                        "prompt": float(m.get("pricing", {}).get("prompt", 0)),
                        "completion": float(m.get("pricing", {}).get("completion", 0)),
                        "prompt_1m": float(m.get("pricing", {}).get("prompt", 0)) * 1_000_000,
                        "completion_1m": float(m.get("pricing", {}).get("completion", 0)) * 1_000_000
                    },
                    "context_length": m.get("context_length", 0),
                    "max_output_tokens": m.get("top_provider", {}).get("max_completion_tokens", 0),
                    "capabilities": extract_capabilities(m.get("description", ""), m["id"])
                })
            return sorted(models, key=lambda x: x["name"])
    except Exception as e:
        print(f"Error fetching OpenRouter: {e}")
        return []

def get_google_access_token():
    """Generate a Google access token using service account."""
    try:
        from google.auth.transport.requests import Request as AuthRequest
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
        creds = service_account.Credentials.from_service_account_file(
            VERTEX_CREDENTIALS, scopes=scopes)
        creds.refresh(AuthRequest())
        return creds.token
    except Exception as e:
        print(f"Error getting Google token: {e}")
        return None

async def fetch_vertex_model_metadata(model_id: str) -> Dict[str, int]:
    """Fetch model metadata from Vertex AI API using canonical model ID format."""
    token = get_google_access_token()
    if not token:
        print("DEBUG: No token")
        return {}

    # Expected input format: 'vertex_ai/gemini-2.5-flash'
    # Canonical publisher ID: 'publishers/google/models/gemini-2.5-flash'
    model_part = model_id.split("/")[-1]
    url = f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model_part}"
    print(f"DEBUG: Fetching metadata for {model_id} -> URL={url}")

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "max_input_tokens": int(data.get("inputTokenLimit", 0)),
                    "max_output_tokens": int(data.get("outputTokenLimit", 0))
                }
            else:
                print(f"DEBUG: Metadata API Error for {model_part}: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"Exception in fetch_vertex_model_metadata: {e}")
    return {}

    # Vertex model ID format needs to be 'publishers/google/models/{MODEL_ID}'
    # We have 'vertex_ai/{short_id}'
    short_id = model_id.split("/")[-1]
    url = f"https://{DEFAULT_LOCATION}-aiplatform.googleapis.com/v1/publishers/google/models/{short_id}"

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "max_input_tokens": int(data.get("inputTokenLimit", 0)),
                    "max_output_tokens": int(data.get("outputTokenLimit", 0))
                }
            else:
                print(f"Vertex API Error: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"Exception in fetch_vertex_model_metadata: {e}")
    print(f"DEBUG: URL={url}, Token={token[:10]}..."); return {}

async def fetch_vertex_billing_skus() -> List[Dict]:
    """Fetch all Vertex AI Gemini SKUs with capabilities and metadata."""
    loc = DEFAULT_LOCATION
    token = get_google_access_token()
    if not token:
        return []

    try:
        url = "https://cloudbilling.googleapis.com/v1/services/C7E2-9256-1C43/skus"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []

            skus = resp.json().get("skus", [])
            models_data = {}

            for s in skus:
                desc = s.get("description", "")
                regions = s.get("serviceRegions", [])

                if "Gemini" in desc and (loc in regions or "global" in [r.lower() for r in regions]):
                    if any(x in desc for x in ["High Priority", "Provisioned", "Commitment", "Reserved"]):
                        continue

                    name_parts = desc.split(" - ")[0].split(" GA ")[0].strip()
                    if name_parts.startswith("Gemini"):
                        model_name = name_parts
                        short_id = model_name.lower().replace(" ", "-")
                        if short_id not in models_data:
                            # Fetch metadata separately
                            meta = await fetch_vertex_model_metadata(f"vertex_ai/{short_id}")
                            models_data[short_id] = {
                                "id": f"vertex_ai/{short_id}",
                                "name": model_name,
                                "brand": "google",
                                "pricing": {"prompt": 0.0, "completion": 0.0, "prompt_1m": 0.0, "completion_1m": 0.0},
                                "context_length": meta.get("max_input_tokens", 0),
                                "max_output_tokens": meta.get("max_output_tokens", 0),
                                "capabilities": extract_capabilities(desc, short_id)
                            }
                        
                        pricing_info = s.get("pricingInfo", [{}])[0].get("pricingExpression", {})
                        rate = pricing_info.get("tieredRates", [{}])[0].get("unitPrice", {})
                        price_usd = float(rate.get("units", 0)) + (float(rate.get("nanos", 0)) / 1e9)
                        
                        if "Input" in desc:
                            models_data[short_id]["pricing"]["prompt"] = price_usd
                            models_data[short_id]["pricing"]["prompt_1m"] = price_usd * 1_000_000
                        elif "Output" in desc:
                            models_data[short_id]["pricing"]["completion"] = price_usd
                            models_data[short_id]["pricing"]["completion_1m"] = price_usd * 1_000_000

            return list(models_data.values())
    except Exception as e:
        print(f"Error fetching Vertex SKUs: {e}")
        return []

async def fetch_vertex_publisher_models(client: httpx.AsyncClient, token: str, proj: str, loc: str) -> List[str]:
    """Fetch foundation models using the modern unified google-genai SDK."""
    try:
        from google import genai
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
        creds = service_account.Credentials.from_service_account_file(VERTEX_CREDENTIALS, scopes=scopes)
        
        client_genai = genai.Client(vertexai=True, project=proj, location=loc, credentials=creds)
        
        available_ids = []
        for model in client_genai.models.list():
            model_id = model.name.split("/")[-1]
            if "gemini" in model_id.lower():
                print(f"DEBUG: Found model: {model.name}"); available_ids.append(model_id)
        
        available_ids.extend([
            "gemini-flash-latest", "gemini-pro-latest", "gemini-flash-lite-latest",
            "gemini-2.0-flash-exp", "gemini-1.5-pro-latest", "gemini-1.5-flash-latest",
            "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-pro"
        ])
        return list(set(available_ids))
    except Exception as e:
        print(f"GenAI SDK Error: {e}")
        return ["gemini-3.5-flash", "gemini-3.5-pro", "gemini-3.1-flash", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]

async def test_model_availability(client: httpx.AsyncClient, model_id: str) -> bool:
    """Send a tiny prompt to LiteLLM proxy to test if model is available."""
    try:
        headers = {"Authorization": f"Bearer {MASTER_KEY}", "Content-Type": "application/json"}
        payload = {"model": model_id, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
        resp = await client.post(PROXY_URL, headers=headers, json=payload, timeout=5.0)
        return resp.status_code == 200
    except: return False

async def verify_and_cache_vertex_models():
    """Concurrently verify a list of potential Gemini models (2026 series)."""
    print(f"Starting definitive verification for {DEFAULT_LOCATION}...")
    proj = DEFAULT_PROJECT
    loc = DEFAULT_LOCATION
    token = get_google_access_token()

    if not os.path.exists(VERTEX_CREDENTIALS) or not proj:
        app_state["vx_models"] = []
        return

    candidates = {}
    try:
        async with httpx.AsyncClient() as client:
            api_ids = await fetch_vertex_publisher_models(client, token, proj, loc)
            for a_id in api_ids:
                candidates[f"vertex_ai/{a_id}"] = {
                    "id": f"vertex_ai/{a_id}",
                    "name": a_id.replace("-", " ").title(),
                    "brand": "google",
                    "pricing": {"prompt": 0.0, "completion": 0.0, "prompt_1m": 0.0, "completion_1m": 0.0},
                    "context_length": "Variable",
                    "capabilities": extract_capabilities("", a_id)
                }

            billing_models = await fetch_vertex_billing_skus()
            for b_m in billing_models:
                candidates[b_m["id"]] = b_m

            # Fallback pricing
            for c_id, c_data in candidates.items():
                m_short = c_id.split("/")[-1]
                base_name = m_short
                if m_short not in FALLBACK_PRICING:
                    parts = m_short.split("-")
                    if len(parts) > 3: base_name = "-".join(parts[:3])
                if base_name in FALLBACK_PRICING:
                    fb = FALLBACK_PRICING[base_name]
                    if c_data["pricing"]["prompt_1m"] == 0: c_data["pricing"]["prompt_1m"] = fb["prompt_1m"]
                    if c_data["pricing"]["completion_1m"] == 0: c_data["pricing"]["completion_1m"] = fb["completion_1m"]

            verified_models = []
            semaphore = asyncio.Semaphore(20)
            async def check(m_data):
                async with semaphore:
                    try:
                        headers = {"Authorization": f"Bearer {MASTER_KEY}", "Content-Type": "application/json"}
                        payload = {"model": m_data["id"], "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
                        resp = await client.post(PROXY_URL, headers=headers, json=payload, timeout=10.0)
                        if resp.status_code == 200: print(f"DEBUG: Verified model: {m_data['id']}"); return m_data
                        else: print(f"DEBUG: Model {m_data['id']} failed ping: {resp.status_code} - {resp.text}")
                    except: pass
                return None
            
            tasks = [check(m_data) for m_data in candidates.values()]
            results = await asyncio.gather(*tasks)
            verified_models = [r for r in results if r]
            
        verified_models = sorted(verified_models, key=lambda x: x["name"])
        app_state["vx_models"] = verified_models
        app_state["last_verification_time"] = time.time()
        with open(CACHE_FILE, "w") as f:
            json.dump({"timestamp": app_state["last_verification_time"], "models": verified_models}, f)
            
    finally:
        print(f"Vertex verification finished. Found {len(app_state['vx_models'])} functional models.")

async def initial_load_models():
    """Load OpenRouter and check cache for Vertex on startup."""
    app_state["or_models"] = await get_openrouter_models()
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                cache_data = json.load(f)
                if time.time() - cache_data.get("timestamp", 0) < (CACHE_EXPIRY_DAYS * 24 * 3600):
                    models = cache_data.get("models", [])
                    # Safeguard: Ensure capabilities exist for all cached models
                    for m in models:
                        if "capabilities" not in m:
                            m["capabilities"] = extract_capabilities("", m["id"])
                    app_state["vx_models"] = models
                    app_state["last_verification_time"] = cache_data.get("timestamp", 0)
                    return
    except: pass
    asyncio.create_task(verify_and_cache_vertex_models())

@asynccontextmanager
async def lifespan(app: FastAPI):
    await initial_load_models()
    yield

app = FastAPI(lifespan=lifespan)

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
async def test_model(model_id: str = Form(...)):
    try:
        headers = {"Authorization": f"Bearer {MASTER_KEY}", "Content-Type": "application/json"}
        payload = {"model": model_id, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 10}
        async with httpx.AsyncClient() as client:
            resp = await client.post(PROXY_URL, headers=headers, json=payload, timeout=15.0)
            if resp.status_code == 200:
                return {"status": "success", "response": resp.json()["choices"][0]["message"]["content"]}
            return {"status": "error", "message": resp.text}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.post("/force-refresh")
async def force_refresh():
    if os.path.exists(CACHE_FILE):
        try: os.remove(CACHE_FILE)
        except: pass
    app_state["or_models"] = await get_openrouter_models()
    await verify_and_cache_vertex_models()
    return {"status": "success"}

@app.post("/restart-litellm")
async def restart_litellm():
    try:
        import docker
        client = docker.from_env()
        client.containers.get("litellm").restart()
        return {"status": "success"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.get("/api/config")
async def get_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f) or {}
            model_list = config.get("model_list", [])
            # Extract IDs from litellm_params.model
            selected_ids = [m.get("litellm_params", {}).get("model") for m in model_list if m.get("litellm_params", {}).get("model")]
            return {"selected_ids": selected_ids}
    except Exception as e:
        print(f"DEBUG: URL={url}"); return {"error": str(e)}












@app.get("/debug-publisher-models")
async def debug_publisher_models():
    token = get_google_access_token()
    if not token: return {"error": "No token"}
    url = f"https://aiplatform.googleapis.com/v1/projects/{DEFAULT_PROJECT}/locations/{DEFAULT_LOCATION}/publishers/google/models"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                # Return only models with "gemini" in their name
                return [m.get("name") for m in resp.json().get("models", []) if "gemini" in m.get("name", "").lower()]
            return {"error": resp.text}
        except Exception as e:
            return {"error": str(e)}




@app.post("/sync")
async def sync_models(request: Request):
    form_data = await request.form()
    selected_ids = form_data.getlist("models")
    all_models = app_state["or_models"] + app_state["vx_models"]
    model_map = {m["id"]: m for m in all_models}
    with open(CONFIG_PATH, "r") as f: config = yaml.safe_load(f) or {}
    new_model_list = []
    for mid in selected_ids:
        m_data = model_map.get(mid, {})
        pricing = m_data.get("pricing", {})
        # Get context window and other metadata
        ctx = m_data.get("context_length"); print(f"DEBUG: mid={mid}, ctx={ctx}")
        max_out = m_data.get("max_output_tokens") or m_data.get("max_completion_tokens")
        
        try:
            ctx_int = int(ctx)
        except (TypeError, ValueError):
            ctx_int = None
        
        try:
            max_out_int = int(max_out)
        except (TypeError, ValueError):
            max_out_int = None
            
        entry = {
            "model_name": mid.split("/")[-1],
            "litellm_params": {"model": mid},
            "model_info": {
                "id": mid,
                "input_cost_per_token": pricing.get("prompt", 0),
                "output_cost_per_token": pricing.get("completion", 0)
            }
        }
        if ctx_int:
            entry["model_info"]["max_input_tokens"] = ctx_int
        if max_out_int:
            entry["model_info"]["max_output_tokens"] = max_out_int
        
        # Add additional common metadata if available
        if "capabilities" in m_data:
            entry["model_info"]["capabilities"] = m_data["capabilities"]
        if "brand" in m_data:
            entry["model_info"]["brand"] = m_data["brand"]
        # Look for version information in common fields
        version = m_data.get("version") or m_data.get("model_version")
        if version:
            entry["model_info"]["version"] = version
        if mid.startswith("openrouter/"):
            entry["litellm_params"]["api_key"] = "os.environ/OPENROUTER_API_KEY"
        elif mid.startswith("vertex_ai/"):
            entry["litellm_params"].update({
                "vertex_project": "os.environ/VERTEX_PROJECT",
                "vertex_location": "os.environ/VERTEX_LOCATION",
                "vertex_credentials": "/app/vertex_credentials.json"
            })
            # For Vertex, also provide character-based pricing as it's common for Gemini
            entry["model_info"]["input_cost_per_character"] = pricing.get("prompt", 0)
            entry["model_info"]["output_cost_per_character"] = pricing.get("completion", 0)
        new_model_list.append(entry)
    wildcards = [m for m in config.get("model_list", []) if "*" in m.get("model_name", "")]
    config["model_list"] = new_model_list + wildcards
    with open(CONFIG_PATH, "w") as f: yaml.safe_dump(config, f, sort_keys=False)
    return {"status": "success", "updated_models": len(new_model_list)}

@app.get("/api/models")
async def api_models():
    return {"openrouter": app_state["or_models"], "vertex": app_state["vx_models"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
