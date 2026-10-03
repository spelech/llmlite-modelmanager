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
from app.database import get_setting, set_setting


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

async def fetch_google_billing_info() -> Dict[str, Any]:
    """Fetch Google Cloud Project Billing status and account info."""
    token = get_google_access_token()
    project = get_app_setting("VERTEX_PROJECT")
    if not token or not project:
        return {"status": "error", "message": "Missing Google token or VERTEX_PROJECT"}

    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Project Billing Info
            p_url = f"https://cloudbilling.googleapis.com/v1/projects/{project}/billingInfo"
            p_resp = await client.get(p_url, headers=headers)
            if p_resp.status_code != 200:
                return {
                    "status": "error",
                    "status_code": p_resp.status_code,
                    "message": p_resp.json().get("error", {}).get("message", "Failed to query GCP Billing API")
                }

            p_data = p_resp.json()
            billing_enabled = p_data.get("billingEnabled", False)
            account_name = p_data.get("billingAccountName", "")
            account_id = account_name.split("/")[-1] if "/" in account_name else account_name

            # 2. Check if Service Account has Billing Account Viewer permission
            iam_viewer = False
            account_details = {}
            if account_name:
                a_url = f"https://cloudbilling.googleapis.com/v1/{account_name}"
                a_resp = await client.get(a_url, headers=headers)
                if a_resp.status_code == 200:
                    iam_viewer = True
                    account_details = a_resp.json()

            return {
                "status": "success",
                "project_id": project,
                "billing_enabled": billing_enabled,
                "billing_account_name": account_name,
                "billing_account_id": account_id,
                "billing_account_display_name": account_details.get("displayName"),
                "billing_account_open": account_details.get("open", True),
                "iam_viewer_granted": iam_viewer
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def fetch_vertex_spend(database_url: Optional[str] = None) -> Dict[str, Any]:
    """Fetch Vertex AI spend metrics from PostgreSQL (LiteLLM_SpendLogs) or LiteLLM Proxy."""
    # Method 1: Try asyncpg direct database query
    db_url = database_url or get_app_setting("LITELLM_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        db_url = "postgresql://litellm:litellm_pass_99@litellm-db:5432/litellm"

    clean_db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    try:
        import asyncpg
        conn = await asyncpg.connect(clean_db_url, timeout=3.0)
        try:
            row = await conn.fetchrow("""
                SELECT 
                    COALESCE(SUM(CASE WHEN "startTime" >= date_trunc('month', CURRENT_DATE) THEN spend ELSE 0 END), 0.0) as current_month_spend,
                    COALESCE(SUM(CASE WHEN "startTime" >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month') AND "startTime" < date_trunc('month', CURRENT_DATE) THEN spend ELSE 0 END), 0.0) as previous_month_spend,
                    COALESCE(SUM(spend), 0.0) as total_spend,
                    COUNT(CASE WHEN "startTime" >= date_trunc('month', CURRENT_DATE) THEN 1 END) as current_month_requests
                FROM "LiteLLM_SpendLogs" 
                WHERE (custom_llm_provider = 'vertex_ai' OR model LIKE 'vertex_ai/%');
            """)

            top_rows = await conn.fetch("""
                SELECT 
                    model,
                    ROUND(SUM(spend)::numeric, 4) as spend,
                    COUNT(*) as requests
                FROM "LiteLLM_SpendLogs"
                WHERE (custom_llm_provider = 'vertex_ai' OR model LIKE 'vertex_ai/%')
                GROUP BY model
                ORDER BY spend DESC
                LIMIT 5;
            """)

            top_models = [
                {"model": r["model"], "spend": float(r["spend"]), "requests": int(r["requests"])}
                for r in top_rows
            ]

            return {
                "status": "success",
                "source": "postgresql",
                "current_month_spend": round(float(row["current_month_spend"]), 4),
                "previous_month_spend": round(float(row["previous_month_spend"]), 4),
                "total_spend": round(float(row["total_spend"]), 4),
                "current_month_requests": int(row["current_month_requests"]),
                "top_models": top_models
            }
        finally:
            await conn.close()
    except Exception as db_err:
        pass

    # Method 2: Fallback to LiteLLM REST API
    try:
        master_key = get_app_setting("LITELLM_MASTER_KEY") or os.environ.get("LITELLM_MASTER_KEY")
        proxy_url = get_app_setting("LITELLM_PROXY_BASE", "http://litellm:4000")
        if master_key:
            headers = {"Authorization": f"Bearer {master_key}"}
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{proxy_url}/global/spend/models", headers=headers)
                if resp.status_code == 200:
                    models_spend = resp.json()
                    vx_models = [
                        m for m in models_spend
                        if "vertex_ai" in m.get("model", "").lower()
                    ]
                    total_vx = sum(float(m.get("total_spend", 0.0)) for m in vx_models)
                    return {
                        "status": "success",
                        "source": "litellm_proxy",
                        "current_month_spend": round(total_vx, 4),
                        "previous_month_spend": 0.0,
                        "total_spend": round(total_vx, 4),
                        "current_month_requests": 0,
                        "top_models": [
                            {"model": m.get("model"), "spend": round(float(m.get("total_spend", 0.0)), 4), "requests": 0}
                            for m in sorted(vx_models, key=lambda x: float(x.get("total_spend", 0.0)), reverse=True)[:5]
                        ]
                    }
    except Exception as api_err:
        pass

    return {
        "status": "error",
        "message": "Unable to connect to database or LiteLLM proxy for spend data",
        "current_month_spend": 0.0,
        "previous_month_spend": 0.0,
        "total_spend": 0.0,
        "current_month_requests": 0,
        "top_models": []
    }

async def check_vertex_budget(notify: bool = True, budget: Optional[float] = None) -> Dict[str, Any]:
    """Evaluate Vertex AI month-to-date spend against budget threshold and trigger alert with cooldown."""
    alert_enabled_str = await get_setting("VERTEX_BUDGET_ALERT_ENABLED", "true")
    alert_enabled = str(alert_enabled_str).lower() in ("true", "1", "yes")

    budget_val = budget
    if budget_val is None:
        budget_str = await get_setting("VERTEX_MONTHLY_BUDGET", "25.0")
        try:
            budget_val = float(budget_str)
        except (ValueError, TypeError):
            budget_val = 25.0

    billing_info = await fetch_google_billing_info()
    spend_info = await fetch_vertex_spend()

    current_month_spend = spend_info.get("current_month_spend", 0.0)
    percent_used = round((current_month_spend / budget_val * 100), 1) if budget_val > 0 else 0.0
    is_over_budget = current_month_spend >= budget_val
    billing_enabled = billing_info.get("billing_enabled", True) if billing_info.get("status") == "success" else True

    result = {
        "status": "success",
        "gcp_billing": billing_info,
        "vertex_spend": spend_info,
        "monthly_budget": budget_val,
        "current_month_spend": current_month_spend,
        "percent_used": percent_used,
        "is_over_budget": is_over_budget,
        "billing_enabled": billing_enabled
    }

    # Alert condition 1: GCP Project Billing Disabled
    if not billing_enabled and notify and alert_enabled:
        from app.notifications import notify_gcp_billing_disabled
        last_alert_str = await get_setting("LAST_GCP_BILLING_DISABLED_ALERT_TIME", "0")
        try:
            last_alert = float(last_alert_str)
        except (ValueError, TypeError):
            last_alert = 0.0
        now = time.time()
        if now - last_alert > 86400 or last_alert == 0.0:
            alert_res = await notify_gcp_billing_disabled(billing_info)
            result["billing_disabled_notification"] = alert_res
            if alert_res.get("status") == "success":
                await set_setting("LAST_GCP_BILLING_DISABLED_ALERT_TIME", str(now))

    # Alert condition 2: Monthly Budget Exceeded
    if is_over_budget and notify and alert_enabled:
        last_time_str = await get_setting("LAST_VERTEX_ALERT_TIME", "0")
        last_spend_str = await get_setting("LAST_VERTEX_ALERT_SPEND", "-1")
        try:
            last_time = float(last_time_str)
            last_spend = float(last_spend_str)
        except (ValueError, TypeError):
            last_time = 0.0
            last_spend = -1.0

        current_time = time.time()
        # Cooldown: 24h OR spend increased by >= $2.00 since last alert
        should_alert = (current_time - last_time > 86400) or (current_month_spend - last_spend >= 2.0) or (last_time == 0.0)

        if should_alert:
            from app.notifications import notify_vertex_budget_exceeded
            alert_res = await notify_vertex_budget_exceeded(
                spend=current_month_spend,
                budget=budget_val,
                top_models=spend_info.get("top_models", []),
                billing_info=billing_info
            )
            result["budget_notification"] = alert_res
            if alert_res.get("status") == "success":
                await set_setting("LAST_VERTEX_ALERT_TIME", str(current_time))
                await set_setting("LAST_VERTEX_ALERT_SPEND", str(current_month_spend))
        else:
            result["budget_notification"] = {"status": "skipped", "message": "Alert cooldown active"}

    return result

