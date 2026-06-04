from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import json
import requests
import yaml
from typing import List, Dict

app = FastAPI()

# Mount templates
templates = Jinja2Templates(directory="app/templates")

# --- Config Paths ---
CONFIG_PATH = os.environ.get("LITELLM_CONFIG", "/app/config/config.yaml")
VERTEX_CREDENTIALS = os.environ.get("VERTEX_CREDENTIALS_PATH", "/app/vertex_credentials.json")
PROXY_URL = "http://litellm:4000/v1/chat/completions"
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-local-wileyriley-gateway-12345")

def get_openrouter_models() -> List[Dict]:
    """Fetch and format OpenRouter models and pricing."""
    try:
        resp = requests.get("https://openrouter.ai/api/v1/models")
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
        return models
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

def get_vertex_models() -> List[Dict]:
    """Fetch Vertex AI models using Google Billing API and regional filtering."""
    proj = os.environ.get("VERTEX_PROJECT")
    loc = os.environ.get("VERTEX_LOCATION", "us-east4")
    
    token = get_google_access_token()
    if not token:
        return []

    try:
        # Use Billing Catalog for regional pricing and availability
        url = "https://cloudbilling.googleapis.com/v1/services/C7E2-9256-1C43/skus"
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            return []
        
        skus = resp.json().get("skus", [])
        models_data = {}
        
        for s in skus:
            desc = s.get("description", "")
            regions = s.get("serviceRegions", [])
            
            # Filter for Gemini models available in our region or global
            if "Gemini" in desc and (loc in regions or "global" in [r.lower() for r in regions]):
                # Heuristic: Extract model name like "Gemini 3.5 Flash"
                name_parts = desc.split(" - ")[0].split(" GA ")[0].strip()
                if name_parts.startswith("Gemini"):
                    model_name = name_parts
                    # Clean up model name for LiteLLM ID (e.g. vertex_ai/gemini-1.5-flash)
                    # We remove version suffixes like "002" unless the user picked them
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
                    
                    # Update pricing if Input/Output is found
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
        print(f"Error fetching Vertex: {e}")
        return []

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    or_models = get_openrouter_models()
    vx_models = get_vertex_models()
    
    or_models.sort(key=lambda x: x['name'])
    vx_models.sort(key=lambda x: x['name'])

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "or_models": or_models, 
            "vx_models": vx_models
        }
    )

@app.post("/test")
async def test_model(model_id: str = Form(...)):
    """Test a model connection through the LiteLLM proxy."""
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
        resp = requests.post(PROXY_URL, headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            return {"status": "success", "response": resp.json()["choices"][0]["message"]["content"]}
        else:
            return {"status": "error", "code": resp.status_code, "message": resp.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/sync")
async def sync_models(request: Request):
    form_data = await request.form()
    selected_ids = form_data.getlist("models")
    
    or_models = get_openrouter_models()
    vx_models = get_vertex_models()
    all_models = or_models + vx_models
    model_map = {m["id"]: m for m in all_models}

    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f) or {}

    new_model_list = []
    for mid in selected_ids:
        if mid in model_map:
            m_data = model_map[mid]
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
