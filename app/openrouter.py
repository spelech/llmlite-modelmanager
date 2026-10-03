import time
import httpx
from typing import List, Dict, Optional, Any
from app.capabilities import extract_capabilities, extract_benchmarks
from app.discovery import classify_model_tier
from app.config import get_app_setting
from app.database import get_setting, set_setting

async def get_openrouter_models() -> List[Dict]:
    """Fetch and format OpenRouter models with capabilities and tiers."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://openrouter.ai/api/v1/models?sort=most-popular")
            if resp.status_code != 200:
                return []
            
            models = []
            for idx, m in enumerate(resp.json().get("data", [])):
                brand = m['id'].split("/")[0] if "/" in m['id'] else "other"
                raw_prompt = float(m.get("pricing", {}).get("prompt", 0))
                raw_completion = float(m.get("pricing", {}).get("completion", 0))
                
                # OpenRouter returns -1 for dynamic routers (e.g. TypeSafe JEV, OpenRouter Auto, Switchyard)
                is_dynamic_router = (raw_prompt < 0 or raw_completion < 0)
                if is_dynamic_router:
                    prompt_val = 0.0
                    completion_val = 0.0
                    prompt_1m = 0.0
                    completion_1m = 0.0
                else:
                    prompt_val = raw_prompt
                    completion_val = raw_completion
                    prompt_1m = raw_prompt * 1_000_000
                    completion_1m = raw_completion * 1_000_000

                pricing_dict = {
                    "prompt": prompt_val,
                    "completion": completion_val,
                    "prompt_1m": prompt_1m,
                    "completion_1m": completion_1m,
                    "is_dynamic_router": is_dynamic_router
                }
                model_item = {
                    "id": f"openrouter/{m['id']}",
                    "name": m.get("name", m["id"]),
                    "brand": brand,
                    "popularity": idx,
                    "pricing": pricing_dict,
                    "max_input_tokens": m.get("context_length", 0),
                    "max_output_tokens": m.get("top_provider", {}).get("max_completion_tokens", 0),
                    "capabilities": extract_capabilities(m.get("description", ""), m["id"]),
                    "benchmarks": extract_benchmarks(m.get("benchmarks"))
                }
                model_item["tier"] = classify_model_tier(model_item)
                models.append(model_item)
            return models
    except Exception as e:
        print(f"Error fetching OpenRouter: {e}")
        return []

async def fetch_openrouter_credits(api_key: Optional[str] = None) -> Dict[str, Any]:
    """Fetch prepaid balance, total usage, and key limits from OpenRouter."""
    key = api_key or get_app_setting("OPENROUTER_API_KEY")
    if not key:
        return {"status": "error", "message": "No OPENROUTER_API_KEY configured"}
    
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            credits_resp = await client.get("https://openrouter.ai/api/v1/credits", headers=headers)
            key_resp = await client.get("https://openrouter.ai/api/v1/auth/key", headers=headers)
            
            credits_data = credits_resp.json().get("data", {}) if credits_resp.status_code == 200 else {}
            key_data = key_resp.json().get("data", {}) if key_resp.status_code == 200 else {}
            
            total_credits = float(credits_data.get("total_credits", 0.0))
            total_usage = float(credits_data.get("total_usage", 0.0))
            balance = round(max(0.0, total_credits - total_usage), 4)
            
            return {
                "status": "success",
                "total_credits": total_credits,
                "total_usage": total_usage,
                "balance": balance,
                "key_label": key_data.get("label"),
                "key_limit": key_data.get("limit"),
                "key_limit_remaining": key_data.get("limit_remaining"),
                "key_usage_monthly": float(key_data.get("usage_monthly", 0.0) or 0.0),
                "is_free_tier": key_data.get("is_free_tier", False)
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def check_openrouter_balance(notify: bool = True, threshold: Optional[float] = None) -> Dict[str, Any]:
    """Evaluate OpenRouter balance against threshold and trigger alert with cooldown."""
    alert_enabled_str = await get_setting("OPENROUTER_BALANCE_ALERT_ENABLED", "true")
    alert_enabled = str(alert_enabled_str).lower() in ("true", "1", "yes")

    threshold_val = threshold
    if threshold_val is None:
        threshold_str = await get_setting("OPENROUTER_LOW_CREDIT_THRESHOLD", "5.0")
        try:
            threshold_val = float(threshold_str)
        except (ValueError, TypeError):
            threshold_val = 5.0

    credit_info = await fetch_openrouter_credits()
    if credit_info.get("status") != "success":
        return credit_info

    balance = credit_info.get("balance", 0.0)
    is_low = balance <= threshold_val
    credit_info["is_low"] = is_low
    credit_info["threshold"] = threshold_val

    if is_low and notify and alert_enabled:
        last_time_str = await get_setting("LAST_OPENROUTER_ALERT_TIME", "0")
        last_balance_str = await get_setting("LAST_OPENROUTER_ALERT_BALANCE", "-1")
        try:
            last_time = float(last_time_str)
            last_balance = float(last_balance_str)
        except (ValueError, TypeError):
            last_time = 0.0
            last_balance = -1.0

        current_time = time.time()
        # Cooldown: 24h OR balance dropped by >= $1.00 since last alert
        should_alert = (current_time - last_time > 86400) or (last_balance - balance >= 1.0) or (last_time == 0.0)
        
        if should_alert:
            from app.notifications import notify_openrouter_low_credit
            alert_res = await notify_openrouter_low_credit(
                balance=balance,
                threshold=threshold_val,
                key_info=credit_info
            )
            credit_info["notification"] = alert_res
            if alert_res.get("status") == "success":
                await set_setting("LAST_OPENROUTER_ALERT_TIME", str(current_time))
                await set_setting("LAST_OPENROUTER_ALERT_BALANCE", str(balance))
        else:
            credit_info["notification"] = {"status": "skipped", "message": "Alert cooldown active"}

    return credit_info
