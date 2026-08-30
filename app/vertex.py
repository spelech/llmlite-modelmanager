import os
import json
import time
import httpx
from typing import List, Dict, Any, Optional
from google.oauth2 import service_account
from google.auth.transport.requests import Request as AuthRequest

from app.config import (
    DEFAULT_VERTEX_CREDS,
    CACHE_FILE,
    DEFAULT_LOCATION,
    DEFAULT_CONFIG_PATH,
    app_state,
    get_app_setting
)
from app.capabilities import extract_capabilities, extract_benchmarks, resolve_benchmarks_for_model, GEMINI_SPECS, FALLBACK_PRICING
from app.discovery import classify_model_tier, process_and_track_discovered_models

def get_google_access_token() -> Optional[str]:
    """Generate a Google access token using service account credentials."""
    try:
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
        creds_path = get_app_setting("VERTEX_CREDENTIALS_PATH", DEFAULT_VERTEX_CREDS)
        if not os.path.exists(creds_path):
            return None
        creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
        creds.refresh(AuthRequest())
        return creds.token
    except Exception as e:
        print(f"Error getting Google token: {e}")
        return None

async def fetch_vertex_model_metadata(model_id: str) -> Dict[str, int]:
    """Fetch technical token limits for a canonical model ID via Vertex AI REST API."""
    token = get_google_access_token()
    if not token:
        return {}
    
    project = get_app_setting("VERTEX_PROJECT")
    location = get_app_setting("VERTEX_LOCATION", DEFAULT_LOCATION)
    if not project:
        return {}
        
    url = f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models/{model_id}"
    
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
    """Fetch pricing data for Gemini models from Google Cloud Billing API."""
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

async def fetch_vertex_publisher_models() -> List[Dict[str, Any]]:
    """
    List all available Google models with dynamic token limits, description, and methods.
    """
    try:
        from google import genai
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
        creds_path = get_app_setting("VERTEX_CREDENTIALS_PATH", DEFAULT_VERTEX_CREDS)
        if not os.path.exists(creds_path):
            raise FileNotFoundError(f"Credentials not found at {creds_path}")
            
        creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
        client = genai.Client(
            vertexai=True,
            project=get_app_setting("VERTEX_PROJECT"),
            location=get_app_setting("VERTEX_LOCATION", DEFAULT_LOCATION),
            credentials=creds
        )
        
        discovered = []
        for model in client.models.list():
            mid = model.name.split("/")[-1]
            if "gemini" in mid.lower() or "imagen" in mid.lower():
                discovered.append({
                    "id": mid,
                    "name": getattr(model, "display_name", None) or mid.replace("-", " ").title(),
                    "description": getattr(model, "description", "") or "",
                    "input_token_limit": getattr(model, "input_token_limit", None),
                    "output_token_limit": getattr(model, "output_token_limit", None),
                    "supported_methods": getattr(model, "supported_generation_methods", []) or []
                })
        if discovered:
            return discovered
    except Exception as e:
        print(f"GenAI SDK Discovery Error: {e}")
        
    # Fallback default models if SDK discovery fails
    default_ids = [
        "gemini-3.7-flash", "gemini-3.7-pro",
        "gemini-2.5-flash", "gemini-2.5-pro",
        "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"
    ]
    return [{"id": mid, "name": mid.replace("-", " ").title(), "description": "", "input_token_limit": None, "output_token_limit": None, "supported_methods": []} for mid in default_ids]

async def verify_and_cache_vertex_models():
    """Discover Vertex models, resolve limits/capabilities/pricing, and cache results."""
    print(f"Starting Vertex discovery for {get_app_setting('VERTEX_LOCATION', DEFAULT_LOCATION)} (Universal Mode)...")
    
    discovered_models = await fetch_vertex_publisher_models()
    pricing_map = await fetch_vertex_billing_skus()
    
    models = []
    seen_ids = set()
    for m in discovered_models:
        mid = m["id"]
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        
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

        # Resolve token limits from dynamic discovery or specifications
        spec = GEMINI_SPECS.get(mid, {"ctx": 1000000, "out": 65536})
        if mid not in GEMINI_SPECS:
            base_id = "-".join(mid.split("-")[:3])
            spec = GEMINI_SPECS.get(base_id, spec)

        max_in = m.get("input_token_limit") or spec["ctx"]
        max_out = m.get("output_token_limit") or spec["out"]

        model_item = {
            "id": f"vertex_ai/{mid}",
            "name": m.get("name") or mid.replace("-", " ").title(),
            "brand": "google",
            "pricing": {
                "prompt": p_data["prompt_1m"] / 1_000_000,
                "completion": p_data["completion_1m"] / 1_000_000,
                "prompt_1m": p_data["prompt_1m"],
                "completion_1m": p_data["completion_1m"]
            },
            "max_input_tokens": max_in,
            "max_output_tokens": max_out,
            "capabilities": extract_capabilities(m.get("description", ""), mid, m.get("supported_methods")),
            "benchmarks": resolve_benchmarks_for_model(mid, app_state.get("or_models", []))
        }
        model_item["tier"] = classify_model_tier(model_item)
        models.append(model_item)

    verified_models = sorted(models, key=lambda x: x["name"])
    app_state["vx_models"] = verified_models
    app_state["last_verification_time"] = time.time()
    
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({"timestamp": app_state["last_verification_time"], "models": verified_models}, f)
    except Exception as e:
        print(f"Error saving Vertex cache: {e}")
        
    print(f"Vertex discovery finished. Found {len(verified_models)} models.")
    
    # Track discovered models and trigger alerts
    await process_and_track_discovered_models(app_state["or_models"] + verified_models, notify=True)

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
