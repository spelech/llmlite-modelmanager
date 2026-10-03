import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.openrouter import fetch_openrouter_credits, check_openrouter_balance
from app.notifications import notify_openrouter_low_credit

@pytest.mark.asyncio
async def test_fetch_openrouter_credits_success():
    mock_credits_resp = MagicMock()
    mock_credits_resp.status_code = 200
    mock_credits_resp.json.return_value = {
        "data": {
            "total_credits": 50.0,
            "total_usage": 42.50
        }
    }

    mock_key_resp = MagicMock()
    mock_key_resp.status_code = 200
    mock_key_resp.json.return_value = {
        "data": {
            "label": "test-key",
            "limit": 20.0,
            "limit_remaining": 15.0,
            "usage_monthly": 2.50,
            "is_free_tier": False
        }
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.side_effect = [mock_credits_resp, mock_key_resp]
        res = await fetch_openrouter_credits(api_key="sk-or-v1-test")

        assert res["status"] == "success"
        assert res["total_credits"] == 50.0
        assert res["total_usage"] == 42.50
        assert res["balance"] == 7.50
        assert res["key_label"] == "test-key"
        assert res["key_limit"] == 20.0
        assert res["key_limit_remaining"] == 15.0

@pytest.mark.asyncio
async def test_fetch_openrouter_credits_no_key():
    with patch("app.openrouter.get_app_setting", return_value=None):
        res = await fetch_openrouter_credits(api_key=None)
        assert res["status"] == "error"
        assert "No OPENROUTER_API_KEY configured" in res["message"]

@pytest.mark.asyncio
async def test_check_openrouter_balance_healthy():
    credit_data = {
        "status": "success",
        "total_credits": 50.0,
        "total_usage": 35.0,
        "balance": 15.0,
        "key_label": "test-key"
    }

    with patch("app.openrouter.fetch_openrouter_credits", new_callable=AsyncMock) as mock_fetch, \
         patch("app.openrouter.get_setting", new_callable=AsyncMock) as mock_get_setting:
        mock_fetch.return_value = credit_data
        mock_get_setting.side_effect = lambda k, d=None: "5.0" if k == "OPENROUTER_LOW_CREDIT_THRESHOLD" else "true"

        res = await check_openrouter_balance(notify=True)
        assert res["is_low"] is False
        assert "notification" not in res

@pytest.mark.asyncio
async def test_check_openrouter_balance_low_triggers_alert():
    credit_data = {
        "status": "success",
        "total_credits": 50.0,
        "total_usage": 47.0,
        "balance": 3.0,
        "key_label": "test-key"
    }

    with patch("app.openrouter.fetch_openrouter_credits", new_callable=AsyncMock) as mock_fetch, \
         patch("app.openrouter.get_setting", new_callable=AsyncMock) as mock_get_setting, \
         patch("app.openrouter.set_setting", new_callable=AsyncMock) as mock_set_setting, \
         patch("app.notifications.notify_openrouter_low_credit", new_callable=AsyncMock) as mock_notify:
        
        mock_fetch.return_value = credit_data
        # Last alert time 0 means never alerted
        mock_get_setting.side_effect = lambda k, d=None: "0" if "TIME" in k else ("5.0" if "THRESHOLD" in k else "true")
        mock_notify.return_value = {"status": "success"}

        res = await check_openrouter_balance(notify=True)
        assert res["is_low"] is True
        assert res["notification"]["status"] == "success"
        mock_notify.assert_called_once()
        assert mock_set_setting.call_count >= 1

@pytest.mark.asyncio
async def test_notify_openrouter_low_credit_payload():
    with patch("app.notifications.get_notification_config", return_value={
        "enabled": True,
        "apprise_url": "http://apprise:8000/notify/system"
    }), patch("app.notifications.send_notification", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "success"}

        res = await notify_openrouter_low_credit(balance=2.50, threshold=5.0, key_info={"total_usage": 47.50, "key_label": "test-key"})
        assert res["status"] == "success"
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert "OpenRouter Credit Alert: $2.50 Remaining" in call_kwargs["title"]
        assert "$2.50" in call_kwargs["body"]
        assert call_kwargs["notification_type"] == "warning"

@pytest.mark.asyncio
async def test_get_openrouter_models_handles_dynamic_router_sentinel_pricing():
    from app.openrouter import get_openrouter_models

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {
                "id": "typesafe/jev-router",
                "name": "TypeSafe: Jev Router",
                "description": "Adaptive dynamic router for multi-model queries",
                "context_length": 128000,
                "pricing": {
                    "prompt": "-1",
                    "completion": "-1"
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = mock_resp
        models = await get_openrouter_models()
        assert len(models) == 1
        m = models[0]
        assert m["id"] == "openrouter/typesafe/jev-router"
        pricing = m["pricing"]
        assert pricing["is_dynamic_router"] is True
        assert pricing["prompt_1m"] == 0.0
        assert pricing["completion_1m"] == 0.0
        assert pricing["prompt"] == 0.0
        assert pricing["completion"] == 0.0

