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
                    "format": "markdown",
                    "tag": "all"
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

async def notify_price_changes(price_changed_models: List[Dict]) -> Dict[str, any]:
    """Send alert when notable models have price reductions or increases."""
    config = await get_notification_config()
    notify_price = str(await get_setting("NOTIFY_ON_PRICE_CHANGE", "true")).lower() in ("true", "1", "yes")
    if not config["enabled"] or not notify_price or not price_changed_models:
        return {"status": "skipped", "message": "Price change notifications disabled or empty list"}

    lines = ["**Model Pricing Updates Detected**\n"]
    for m in price_changed_models[:6]:
        direction = m.get("price_change_direction", "change")
        icon = "📉" if direction == "drop" else "📈"
        pct = m.get("price_change_pct", 0.0)
        sign = "+" if pct > 0 else ""
        prev_str = f"${m.get('prev_prompt_1m', 0):.2f}/${m.get('prev_completion_1m', 0):.2f}"
        new_str = f"${m.get('new_prompt_1m', 0):.2f}/${m.get('new_completion_1m', 0):.2f}"
        lines.append(f"{icon} **{m.get('name', m['id'])}** ({sign}{pct:.1f}%)\n  • Before: {prev_str} -> **Now: {new_str}** / 1M\n")

    if len(price_changed_models) > 6:
        lines.append(f"• *...and {len(price_changed_models) - 6} other model price updates*\n")

    drops = [m for m in price_changed_models if m.get("price_change_direction") == "drop"]
    title = f"📉 Price Drop Alert ({len(drops)} models)" if len(drops) >= len(price_changed_models) / 2 else f"🏷️ Model Price Updates ({len(price_changed_models)} models)"

    return await send_notification(
        title=title,
        body="\n".join(lines).strip(),
        notification_type="info",
        tags="money_with_wings,chart_with_downwards_trend,robot",
    )

async def notify_openrouter_low_credit(
    balance: float,
    threshold: float = 5.0,
    key_info: Optional[Dict] = None
) -> Dict[str, any]:
    """Send alert when OpenRouter prepaid credits fall below threshold."""
    config = await get_notification_config()
    if not config["enabled"]:
        return {"status": "skipped", "message": "Notifications disabled"}

    title = f"⚠️ OpenRouter Credit Alert: ${balance:.2f} Remaining"
    total_usage = key_info.get("total_usage") if key_info else None
    usage_line = f"• **Total Usage**: `${total_usage:.2f}`\n" if total_usage is not None else ""
    key_label = key_info.get("key_label") if key_info else None
    label_line = f"• **Key**: `{key_label}`\n" if key_label else ""

    body = (
        f"**OpenRouter Low Balance Warning**\n\n"
        f"• **Remaining Balance**: `${balance:.2f}`\n"
        f"• **Alert Threshold**: `${threshold:.2f}`\n"
        f"{label_line}"
        f"{usage_line}"
        f"• **Checked At**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n\n"
        f"Please top up your OpenRouter account at [openrouter.ai/credits](https://openrouter.ai/credits) "
        f"to prevent service interruptions for LiteLLM models."
    )
    return await send_notification(
        title=title,
        body=body,
        notification_type="warning",
        tags="moneybag,warning,robot",
        click_url="https://openrouter.ai/credits"
    )

async def notify_vertex_budget_exceeded(
    spend: float,
    budget: float,
    top_models: Optional[List[Dict]] = None,
    billing_info: Optional[Dict] = None
) -> Dict[str, any]:
    """Send alert when Vertex AI month-to-date spend exceeds budget threshold."""
    config = await get_notification_config()
    if not config["enabled"]:
        return {"status": "skipped", "message": "Notifications disabled"}

    percent = (spend / budget * 100) if budget > 0 else 100.0
    title = f"⚠️ Vertex AI Budget Alert: ${spend:.2f} MTD ({percent:.0f}%)"

    model_lines = []
    if top_models:
        model_lines.append("\n**Top Spending Models (MTD):**")
        for m in top_models[:4]:
            m_name = m.get("model", "").replace("vertex_ai/", "")
            m_spend = m.get("spend", 0.0)
            m_reqs = m.get("requests", 0)
            model_lines.append(f"• `{m_name}`: ${m_spend:.2f} ({m_reqs} reqs)")
    top_models_str = "\n".join(model_lines) if model_lines else ""

    proj = billing_info.get("project_id", "poised-receiver-492017-j6") if billing_info else "poised-receiver-492017-j6"
    acct = billing_info.get("billing_account_id", "0158E6-19F950-6A6D66") if billing_info else "0158E6-19F950-6A6D66"

    body = (
        f"**Google Vertex AI Monthly Budget Alert**\n\n"
        f"• **Month-to-Date Spend**: `${spend:.2f}`\n"
        f"• **Monthly Budget Limit**: `${budget:.2f}`\n"
        f"• **Budget Utilized**: `{percent:.1f}%`\n"
        f"• **GCP Project**: `{proj}`\n"
        f"• **Billing Account**: `{acct}`\n"
        f"{top_models_str}\n\n"
        f"• **Checked At**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n\n"
        f"Review usage and billing in Google Cloud Console or update budget thresholds in LiteLLM Manager."
    )
    return await send_notification(
        title=title,
        body=body,
        notification_type="warning",
        tags="moneybag,warning,google",
        click_url=f"https://console.cloud.google.com/billing/{acct}"
    )

async def notify_gcp_billing_disabled(billing_info: Dict) -> Dict[str, any]:
    """Send urgent alert when Google Cloud Project billing has been disabled."""
    config = await get_notification_config()
    if not config["enabled"]:
        return {"status": "skipped", "message": "Notifications disabled"}

    proj = billing_info.get("project_id", "unknown")
    acct = billing_info.get("billing_account_id", "unknown")

    title = f"🚨 Google Cloud Billing Disabled: {proj}"
    body = (
        f"**CRITICAL: Google Cloud Project Billing Is Disabled**\n\n"
        f"• **Project**: `{proj}`\n"
        f"• **Billing Account**: `{acct}`\n"
        f"• **Detected At**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n\n"
        f"All Vertex AI model invocations and Gemini API requests will fail until billing is re-enabled.\n"
        f"Please check your Google Cloud Billing Account payment method immediately."
    )
    return await send_notification(
        title=title,
        body=body,
        notification_type="failure",
        tags="rotating_light,skull,google",
        click_url=f"https://console.cloud.google.com/billing/{acct}"
    )

