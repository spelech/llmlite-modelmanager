import os
import time
import httpx
from typing import Dict, Any, Optional

from app.config import get_app_setting
from app.database import get_setting, set_setting
from app.vertex import get_google_access_token


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
    except Exception:
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
    except Exception:
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
