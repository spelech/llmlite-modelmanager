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

async def get_openrouter_models() -> List[Dict]:
    """Fetch and format OpenRouter models and pricing asynchronously."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://openrouter.ai/api/v1/models")
            if resp.status_code != 200:
                return []
            
            models = []
            for m in resp.json().get("data", []):
                models.append({
                    "id": f"openrouter/{m['id']}",
                    "name": m["name"],
                    "pricing": {
                        "prompt": float(m.get("pricing", {}).get("prompt", 0)),
                        "completion": float(m.get("pricing", {}).get("completion", 0)),
                        "prompt_1m": float(m.get("pricing", {}).get("prompt", 0)) * 1_000_000,
                        "completion_1m": float(m.get("pricing", {}).get("completion", 0)) * 1_000_000
                    },
                    "context_length": m.get("context_length", 0)
                })
            return sorted(models, key=lambda x: x["name"])
    except Exception as e:
        print(f"Error fetching OpenRouter: {e}")
        return []

def get_google_access_token():
    """Generate a Google access token using service account."""
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as AuthRequest
        
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
        creds = service_account.Credentials.from_service_account_file(
            VERTEX_CREDENTIALS, scopes=scopes)
        creds.refresh(AuthRequest())
        return creds.token
    except Exception as e:
        print(f"Error getting Google token: {e}")
        return None

async def fetch_vertex_billing_skus() -> List[Dict]:
    """Fetch all Vertex AI Gemini SKUs from Billing API."""
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
                    name_parts = desc.split(" - ")[0].split(" GA ")[0].strip()
                    if name_parts.startswith("Gemini"):
                        model_name = name_parts
                        short_id = model_name.lower().replace(" ", "-")
                        if short_id not in models_data:
                            models_data[short_id] = {
                                "id": f"vertex_ai/{short_id}",
                                "name": model_name,
                                "pricing": {
                                    "prompt": 0.0, 
                                    "completion": 0.0,
                                    "prompt_1m": 0.0,
                                    "completion_1m": 0.0
                                },
                                "context_length": "Variable"
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

            return sorted(list(models_data.values()), key=lambda x: x["name"])
    except Exception as e:
        print(f"Error fetching Vertex SKUs: {e}")
        return []

async def fetch_vertex_publisher_models(client: httpx.AsyncClient, token: str, proj: str, loc: str) -> List[str]:
    """Fetch exact list of available foundation models via v1beta1 REST API."""
    api_versions = ["v1beta1", "v1"]
    discovered_ids = set()
    headers = {"Authorization": f"Bearer {token}"}
    
    for ver in api_versions:
        url = f"https://{loc}-aiplatform.googleapis.com/{ver}/projects/{proj}/locations/{loc}/publishers/google/models"
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                models_data = resp.json().get("models", [])
                for m in models_data:
                    name_path = m.get("name", "")
                    if "/models/" in name_path:
                        model_id = name_path.split("/models/")[-1]
                        if "gemini" in model_id.lower():
                            discovered_ids.add(model_id)
                if discovered_ids: break
        except Exception: pass
    return list(discovered_ids)

async def test_model_availability(client: httpx.AsyncClient, model_id: str) -> bool:
    """Send a tiny prompt to LiteLLM proxy to test if model is available."""
    try:
        headers = {
            "Authorization": f"Bearer {MASTER_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1
        }
        resp = await client.post(PROXY_URL, headers=headers, json=payload, timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False

async def verify_and_cache_vertex_models():
    """Fetch all possible models from Billing/API and concurrently verify them."""
    print(f"Starting fast concurrent verification of Vertex models in {DEFAULT_LOCATION}...")
    
    proj = DEFAULT_PROJECT
    loc = DEFAULT_LOCATION
    token = get_google_access_token()
    
    if not token or not proj:
        print("Missing credentials or project ID for Vertex.")
        app_state["vx_models"] = []
        return

    try:
        async with httpx.AsyncClient() as client:
            # 1. Gather all candidates from Billing API and Publisher API
            all_billing_skus = await fetch_vertex_billing_skus()
            available_api_ids = await fetch_vertex_publisher_models(client, token, proj, loc)
            
            candidates = {}
            for m_id in available_api_ids:
                candidates[f"vertex_ai/{m_id}"] = {
                    "id": f"vertex_ai/{m_id}",
                    "name": m_id.replace("-", " ").title(),
                    "pricing": {"prompt": 0, "completion": 0, "prompt_1m": 0, "completion_1m": 0},
                    "context_length": "Variable"
                }
                
            for sku in all_billing_skus:
                m_id = sku["id"]
                if m_id not in candidates:
                    candidates[m_id] = sku
                else:
                    if sku["pricing"]["prompt"] > 0:
                        candidates[m_id]["pricing"]["prompt"] = sku["pricing"]["prompt"]
                        candidates[m_id]["pricing"]["prompt_1m"] = sku["pricing"]["prompt_1m"]
                    if sku["pricing"]["completion"] > 0:
                        candidates[m_id]["pricing"]["completion"] = sku["pricing"]["completion"]
                        candidates[m_id]["pricing"]["completion_1m"] = sku["pricing"]["completion_1m"]

            # 2. Concurrently verify all candidates (Ping Sweep)
            verified_models = []
            semaphore = asyncio.Semaphore(15)

            async def check_candidate(m_data):
                async with semaphore:
                    if await test_model_availability(client, m_data["id"]):
                        return m_data
                    return None

            tasks = [check_candidate(m_data) for m_data in candidates.values()]
            results = await asyncio.gather(*tasks)
            
            for res in results:
                if res:
                    verified_models.append(res)
            
        verified_models = sorted(verified_models, key=lambda x: x["name"])
        app_state["vx_models"] = verified_models
        app_state["last_verification_time"] = time.time()
        
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump({
                    "timestamp": app_state["last_verification_time"],
                    "models": verified_models
                }, f)
        except Exception:
            pass
            
    finally:
        print(f"Vertex verification completed. {len(app_state['vx_models'])} verified models found.")

async def initial_load_models():
    """Load OpenRouter and check cache for Vertex on startup."""
    app_state["or_models"] = await get_openrouter_models()
    
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                cache_data = json.load(f)
                cache_age = time.time() - cache_data.get("timestamp", 0)
                if cache_age < (CACHE_EXPIRY_DAYS * 24 * 3600):
                    print("Loaded Vertex models from cache.")
                    app_state["vx_models"] = cache_data.get("models", [])
                    app_state["last_verification_time"] = cache_data.get("timestamp", 0)
                    return
    except Exception as e:
        print(f"Cache load error: {e}")
        
    asyncio.create_task(verify_and_cache_vertex_models())

@asynccontextmanager
async def lifespan(app: FastAPI):
    await initial_load_models()
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "or_models": app_state["or_models"], 
            "vx_models": app_state["vx_models"],
            "version": APP_VERSION,
            "build_time": APP_BUILD_TIME
        }
    )

@app.post("/test")
async def test_model(model_id: str = Form(...)):
    """Test a model connection through the LiteLLM proxy (manual UI trigger)."""
    try:
        headers = {
            "Authorization": f"Bearer {MASTER_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "ping. reply with pong"}],
            "max_tokens": 10
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(PROXY_URL, headers=headers, json=payload, timeout=15.0)
            if resp.status_code == 200:
                return {"status": "success", "response": resp.json()["choices"][0]["message"]["content"]}
            else:
                return {"status": "error", "code": resp.status_code, "message": resp.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/force-refresh")
async def force_refresh():
    """Force clear the cache and re-run verification."""
    if os.path.exists(CACHE_FILE):
        try:
            os.remove(CACHE_FILE)
        except:
            pass
    
    app_state["or_models"] = await get_openrouter_models()
    await verify_and_cache_vertex_models()
    
    return {"status": "success", "message": "Verification complete."}

@app.post("/restart-litellm")
async def restart_litellm():
    """Restart the LiteLLM proxy container using Docker SDK."""
    try:
        import docker
        client = docker.from_env()
        container = client.containers.get("litellm")
        container.restart()
        return {"status": "success", "message": "LiteLLM container restarted successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/sync")
async def sync_models(request: Request):
    form_data = await request.form()
    selected_ids = form_data.getlist("models")
    
    all_models = app_state["or_models"] + app_state["vx_models"]
    model_map = {m["id"]: m for m in all_models}

    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f) or {}

    new_model_list = []
    for mid in selected_ids:
        entry = {
            "model_name": mid.split("/")[-1],
            "litellm_params": {
                "model": mid
            }
        }
        if mid.startswith("openrouter/"):
            entry["litellm_params"]["api_key"] = "os.environ/OPENROUTER_API_KEY"
        elif mid.startswith("vertex_ai/"):
            entry["litellm_params"].update({
                "vertex_project": "os.environ/VERTEX_PROJECT",
                "vertex_location": "os.environ/VERTEX_LOCATION",
                "vertex_credentials": "/app/vertex_credentials.json"
            })
        new_model_list.append(entry)

    wildcards = [m for m in config.get("model_list", []) if "*" in m.get("model_name", "")]
    config["model_list"] = new_model_list + wildcards

    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)

    return {"status": "success", "updated_models": len(new_model_list)}

@app.get("/api/models")
async def api_models():
    return {
        "openrouter": app_state["or_models"], 
        "vertex": app_state["vx_models"]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
