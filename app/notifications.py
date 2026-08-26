import httpx
import os
import time
from typing import Dict, List, Optional
from app.database import get_setting

DEFAULT_APPRISE_URL = "http://apprise:8000/notify/system"

async def get_notification_config() -> Dict[str, any]:
    """Retrieve current notification settings."""
    enabled_str = await get_setting("NOTIFICATION_ENABLED", os.environ.get("NOTIFICATION_ENABLED", "true"))
    enabled = str(enabled_str).lower() in ("true", "1", "yes")
    
    apprise_url = await get_setting("APPRISE_URL", os.environ.get("APPRISE_URL", DEFAULT_APPRISE_URL))
    notify_unavailable = str(await get_setting("NOTIFY_ON_UNAVAILABLE", "true")).lower() in ("true", "1", "yes")
    notify_trending = str(await get_setting("NOTIFY_ON_TRENDING", "true")).lower() in ("true", "1", "yes")
    
    return {
        "enabled": enabled,
        "apprise_url": apprise_url,
        "notify_unavailable": notify_unavailable,
        "notify_trending": notify_trending,
    }

async def send_notification(
    title: str,
    body: str,
    notification_type: str = "info",
    tags: str = "robot,brain",
    click_url: Optional[str] = "https://llm-modelmanager.wileyriley.com",
    override_url: Optional[str] = None
) -> Dict[str, any]:
    """
    Sends an alert via Apprise API or Ntfy endpoint.
    """
    config = await get_notification_config()
    target_url = override_url or config["apprise_url"]
    
    if not target_url:
        return {"status": "skipped", "message": "No notification URL configured"}
    
    if not override_url and not config["enabled"]:
        return {"status": "skipped", "message": "Notifications are disabled in settings"}

    headers = {}
    payload = None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Check if this is an Apprise API URL (e.g., http://apprise:8000/notify/... or https://apprise...)
            if "/notify" in target_url or "apprise" in target_url.lower():
                payload = {
                    "title": title,
                    "body": body,
                    "type": notification_type,  # info, success, warning, failure
                    "tags": tags,
                    "format": "markdown"
                }
                if click_url:
                    payload["url"] = click_url
                resp = await client.post(target_url, json=payload)
            else:
                # Assume direct Ntfy server endpoint (e.g., http://ntfy/system or https://ntfy.sh/...)
                headers = {
                    "Title": title,
                    "Priority": "urgent" if notification_type in ("failure", "warning") else "default",
                    "Tags": tags
                }
                if click_url:
                    headers["Click"] = click_url
                resp = await client.post(target_url, content=body.encode("utf-8"), headers=headers)
                
            if 200 <= resp.status_code < 300:
                return {"status": "success", "status_code": resp.status_code}
            else:
                return {"status": "error", "status_code": resp.status_code, "response": resp.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def notify_model_unavailable(model_id: str, error_reason: str) -> Dict[str, any]:
    """Send alert when a configured LiteLLM model fails health check or is unavailable."""
    config = await get_notification_config()
    if not config["enabled"] or not config["notify_unavailable"]:
        return {"status": "skipped", "message": "Model outage notifications disabled"}

    title = f"⚠️ LiteLLM Model Unavailable: {model_id}"
    body = (
        f"**Model Outage Detected**\n\n"
        f"• **Model ID**: `{model_id}`\n"
        f"• **Error**: {error_reason}\n"
        f"• **Detected At**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n\n"
        f"Please check your provider configuration or switch to an alternate model."
    )
    return await send_notification(
        title=title,
        body=body,
        notification_type="failure",
        tags="warning,skull,robot",
    )

async def notify_new_trending_models(new_models: List[Dict]) -> Dict[str, any]:
    """Send alert when new high-popularity models are discovered."""
    config = await get_notification_config()
    if not config["enabled"] or not config["notify_trending"] or not new_models:
        return {"status": "skipped", "message": "Trending notifications disabled or empty list"}

    # Group by tier
    by_tier = {"frontier": [], "moderate": [], "cheap": []}
    for m in new_models:
        tier = m.get("tier", "moderate")
        if tier in by_tier:
            by_tier[tier].append(m)
        else:
            by_tier["moderate"].append(m)

    lines = ["**New Trending Models Discovered**\n"]
    
    tier_emojis = {
        "frontier": "🔥 **Frontier & Flagship**:",
        "moderate": "⚡ **Moderate & Mid-tier**:",
        "cheap": "💡 **Economy & Fast/Cheap**:"
    }

    total_count = 0
    for tier, label in tier_emojis.items():
        tier_list = by_tier[tier]
        if not tier_list:
            continue
        lines.append(label)
        for m in tier_list[:4]:  # limit per tier in single notification
            total_count += 1
            pricing = m.get("pricing", {})
            prompt_cost = pricing.get("prompt_1m", 0.0)
            comp_cost = pricing.get("completion_1m", 0.0)
            ctx = m.get("max_input_tokens", 0)
            ctx_str = f"{ctx // 1000}k ctx" if ctx else "N/A"
            lines.append(f"• `{m['id']}` — ${prompt_cost:.2f}/${comp_cost:.2f} /1M ({ctx_str})")
        if len(tier_list) > 4:
            lines.append(f"• *...and {len(tier_list) - 4} more in {tier}*")
        lines.append("")

    if total_count == 0:
        return {"status": "skipped", "message": "No relevant tiered models to notify"}

    title = f"🚀 {total_count} New Trending LLM{'s' if total_count != 1 else ''} Available"
    body = "\n".join(lines).strip()

    return await send_notification(
        title=title,
        body=body,
        notification_type="info",
        tags="sparkles,robot,rocket",
    )
