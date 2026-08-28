import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.notifications import send_notification, notify_model_unavailable, notify_new_trending_models

@pytest.mark.asyncio
async def test_send_notification_apprise():
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("app.notifications.get_notification_config", return_value={
        "enabled": True,
        "apprise_url": "http://apprise:8000/notify/system",
        "notify_unavailable": True,
        "notify_trending": True
    }), patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await send_notification("Test Alert", "Testing apprise alerts", "info")
        assert res["status"] == "success"
        assert res["status_code"] == 200
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["title"] == "Test Alert"
        assert call_kwargs["json"]["type"] == "info"

@pytest.mark.asyncio
async def test_send_notification_ntfy():
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("app.notifications.get_notification_config", return_value={
        "enabled": True,
        "apprise_url": "http://ntfy:80/models",
        "notify_unavailable": True,
        "notify_trending": True
    }), patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await send_notification("Outage Alert", "Model down", "failure")
        assert res["status"] == "success"
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["headers"]["Title"] == "Outage Alert"
        assert call_kwargs["headers"]["Priority"] == "urgent"

@pytest.mark.asyncio
async def test_send_notification_disabled():
    with patch("app.notifications.get_notification_config", return_value={
        "enabled": False,
        "apprise_url": "http://apprise:8000/notify/system",
        "notify_unavailable": True,
        "notify_trending": True
    }):
        res = await send_notification("Test Alert", "Testing")
        assert res["status"] == "skipped"

@pytest.mark.asyncio
async def test_notify_model_unavailable():
    with patch("app.notifications.send_notification", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "success"}
        with patch("app.notifications.get_notification_config", return_value={
            "enabled": True,
            "apprise_url": "http://apprise:8000/notify/system",
            "notify_unavailable": True,
            "notify_trending": True
        }):
            res = await notify_model_unavailable("openrouter/deepseek/deepseek-r1", "503 Service Unavailable")
            assert res["status"] == "success"
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args.kwargs
            assert "deepseek-r1" in call_kwargs["title"]
            assert call_kwargs["notification_type"] == "failure"

@pytest.mark.asyncio
async def test_notify_new_trending_models():
    models = [
        {
            "id": "openrouter/anthropic/claude-3-7-sonnet",
            "name": "Claude 3.7 Sonnet",
            "tier": "frontier",
            "pricing": {"prompt_1m": 3.0, "completion_1m": 15.0},
            "max_input_tokens": 200000
        },
        {
            "id": "vertex_ai/gemini-2.5-flash",
            "name": "Gemini 2.5 Flash",
            "tier": "cheap",
            "pricing": {"prompt_1m": 0.10, "completion_1m": 0.40},
            "max_input_tokens": 1000000
        }
    ]
    with patch("app.notifications.send_notification", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "success"}
        with patch("app.notifications.get_notification_config", return_value={
            "enabled": True,
            "apprise_url": "http://apprise:8000/notify/system",
            "notify_unavailable": True,
            "notify_trending": True
        }):
            res = await notify_new_trending_models(models)
            assert res["status"] == "success"
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args.kwargs
            assert "2 New Trending LLMs" in call_kwargs["title"]
            assert "Frontier" in call_kwargs["body"]
            assert "Economy" in call_kwargs["body"]
