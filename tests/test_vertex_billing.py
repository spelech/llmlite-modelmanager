import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.vertex import fetch_google_billing_info, fetch_vertex_spend, check_vertex_budget
from app.notifications import notify_vertex_budget_exceeded, notify_gcp_billing_disabled

@pytest.mark.asyncio
async def test_fetch_google_billing_info_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "projects/test-proj/billingInfo",
        "projectId": "test-proj",
        "billingAccountName": "billingAccounts/0158E6-TEST-12345",
        "billingEnabled": True
    }

    mock_acct_resp = MagicMock()
    mock_acct_resp.status_code = 403

    with patch("app.vertex.get_google_access_token", return_value="fake-token"), \
         patch("app.vertex.get_app_setting", return_value="test-proj"), \
         patch("httpx.AsyncClient.get") as mock_get:
        mock_get.side_effect = [mock_resp, mock_acct_resp]

        res = await fetch_google_billing_info()
        assert res["status"] == "success"
        assert res["project_id"] == "test-proj"
        assert res["billing_enabled"] is True
        assert res["billing_account_id"] == "0158E6-TEST-12345"
        assert res["iam_viewer_granted"] is False

@pytest.mark.asyncio
async def test_fetch_google_billing_info_no_token():
    with patch("app.vertex.get_google_access_token", return_value=None):
        res = await fetch_google_billing_info()
        assert res["status"] == "error"
        assert "Missing Google token" in res["message"]

@pytest.mark.asyncio
async def test_fetch_vertex_spend_proxy_fallback():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"model": "vertex_ai/gemini-2.5-flash", "total_spend": 1.25},
        {"model": "vertex_ai/gemini-3.8-flash", "total_spend": 4.50},
        {"model": "openrouter/qwen", "total_spend": 2.00}
    ]

    with patch.dict("sys.modules", {"asyncpg": None}), \
         patch("app.vertex.get_app_setting") as mock_setting, \
         patch("httpx.AsyncClient.get") as mock_get:
        mock_setting.side_effect = lambda k, d=None: "master-key" if k == "LITELLM_MASTER_KEY" else d
        mock_get.return_value = mock_resp

        res = await fetch_vertex_spend()
        assert res["status"] == "success"
        assert res["source"] == "litellm_proxy"
        assert res["total_spend"] == 5.75
        assert len(res["top_models"]) == 2

@pytest.mark.asyncio
async def test_check_vertex_budget_healthy():
    billing_data = {
        "status": "success",
        "project_id": "test-proj",
        "billing_enabled": True,
        "billing_account_id": "0158E6-TEST-12345"
    }
    spend_data = {
        "status": "success",
        "current_month_spend": 5.0,
        "previous_month_spend": 10.0,
        "total_spend": 15.0,
        "top_models": []
    }

    with patch("app.vertex.fetch_google_billing_info", new_callable=AsyncMock) as mock_billing, \
         patch("app.vertex.fetch_vertex_spend", new_callable=AsyncMock) as mock_spend, \
         patch("app.vertex.get_setting", new_callable=AsyncMock) as mock_get_setting:
        mock_billing.return_value = billing_data
        mock_spend.return_value = spend_data
        mock_get_setting.side_effect = lambda k, d=None: "25.0" if k == "VERTEX_MONTHLY_BUDGET" else "true"

        res = await check_vertex_budget(notify=True)
        assert res["status"] == "success"
        assert res["is_over_budget"] is False
        assert res["percent_used"] == 20.0
        assert "budget_notification" not in res

@pytest.mark.asyncio
async def test_check_vertex_budget_exceeded_triggers_alert():
    billing_data = {
        "status": "success",
        "project_id": "test-proj",
        "billing_enabled": True,
        "billing_account_id": "0158E6-TEST-12345"
    }
    spend_data = {
        "status": "success",
        "current_month_spend": 28.50,
        "previous_month_spend": 12.0,
        "total_spend": 40.50,
        "top_models": [{"model": "gemini-3.8-flash", "spend": 20.0, "requests": 150}]
    }

    with patch("app.vertex.fetch_google_billing_info", new_callable=AsyncMock) as mock_billing, \
         patch("app.vertex.fetch_vertex_spend", new_callable=AsyncMock) as mock_spend, \
         patch("app.vertex.get_setting", new_callable=AsyncMock) as mock_get_setting, \
         patch("app.vertex.set_setting", new_callable=AsyncMock) as mock_set_setting, \
         patch("app.notifications.notify_vertex_budget_exceeded", new_callable=AsyncMock) as mock_notify:
        mock_billing.return_value = billing_data
        mock_spend.return_value = spend_data
        def mock_settings(k, d=None):
            if k == "VERTEX_MONTHLY_BUDGET":
                return "25.0"
            if k == "VERTEX_BUDGET_ALERT_ENABLED":
                return "true"
            if "TIME" in k:
                return "0"
            if "SPEND" in k:
                return "-1"
            return d or "true"

        mock_get_setting.side_effect = mock_settings
        mock_notify.return_value = {"status": "success"}


        res = await check_vertex_budget(notify=True)
        assert res["status"] == "success"
        assert res["is_over_budget"] is True
        assert res["percent_used"] == 114.0
        assert res["budget_notification"]["status"] == "success"
        mock_notify.assert_called_once()
        assert mock_set_setting.call_count >= 1

@pytest.mark.asyncio
async def test_check_vertex_budget_billing_disabled_triggers_alert():
    billing_data = {
        "status": "success",
        "project_id": "test-proj",
        "billing_enabled": False,
        "billing_account_id": "0158E6-TEST-12345"
    }
    spend_data = {
        "status": "success",
        "current_month_spend": 2.0,
        "top_models": []
    }

    with patch("app.vertex.fetch_google_billing_info", new_callable=AsyncMock) as mock_billing, \
         patch("app.vertex.fetch_vertex_spend", new_callable=AsyncMock) as mock_spend, \
         patch("app.vertex.get_setting", new_callable=AsyncMock) as mock_get_setting, \
         patch("app.vertex.set_setting", new_callable=AsyncMock) as mock_set_setting, \
         patch("app.notifications.notify_gcp_billing_disabled", new_callable=AsyncMock) as mock_notify:
        mock_billing.return_value = billing_data
        mock_spend.return_value = spend_data
        mock_get_setting.side_effect = lambda k, d=None: "0" if "TIME" in k else "true"
        mock_notify.return_value = {"status": "success"}

        res = await check_vertex_budget(notify=True)
        assert res["billing_enabled"] is False
        assert res["billing_disabled_notification"]["status"] == "success"
        mock_notify.assert_called_once()

@pytest.mark.asyncio
async def test_notify_vertex_budget_exceeded_payload():
    with patch("app.notifications.get_notification_config", return_value={
        "enabled": True,
        "apprise_url": "http://apprise:8000/notify/system"
    }), patch("app.notifications.send_notification", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "success"}

        res = await notify_vertex_budget_exceeded(
            spend=26.50,
            budget=25.0,
            top_models=[{"model": "gemini-3.8-flash", "spend": 22.0, "requests": 110}],
            billing_info={"project_id": "poised-receiver-492017-j6", "billing_account_id": "0158E6-TEST"}
        )
        assert res["status"] == "success"
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert "Vertex AI Budget Alert: $26.50 MTD" in call_kwargs["title"]
        assert "$26.50" in call_kwargs["body"]
        assert "gemini-3.8-flash" in call_kwargs["body"]
        assert call_kwargs["notification_type"] == "warning"

@pytest.mark.asyncio
async def test_notify_gcp_billing_disabled_payload():
    with patch("app.notifications.get_notification_config", return_value={
        "enabled": True,
        "apprise_url": "http://apprise:8000/notify/system"
    }), patch("app.notifications.send_notification", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "success"}

        res = await notify_gcp_billing_disabled({
            "project_id": "poised-receiver-492017-j6",
            "billing_account_id": "0158E6-TEST"
        })
        assert res["status"] == "success"
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert "Google Cloud Billing Disabled: poised-receiver-492017-j6" in call_kwargs["title"]
        assert "CRITICAL" in call_kwargs["body"]
        assert call_kwargs["notification_type"] == "failure"
