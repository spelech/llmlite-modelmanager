import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.mcp_server import (
    list_active_models,
    list_available_models,
    get_trending_models,
    test_model as mcp_test_model,
    add_model,
    remove_model,
    sync_models,
    sync_librechat,
    check_model_health,
    get_settings,
    update_settings,
    send_test_notification,
    set_app_state_ref
)

@pytest.fixture(autouse=True)
def setup_state():
    mock_state = {
        "or_models": [
            {
                "id": "openrouter/anthropic/claude-3.5-sonnet",
                "name": "Claude 3.5 Sonnet",
                "brand": "anthropic",
                "tier": "frontier",
                "popularity": 1,
                "pricing": {"prompt_1m": 3.0, "completion_1m": 15.0}
            },
            {
                "id": "openrouter/deepseek/deepseek-chat",
                "name": "DeepSeek V3",
                "brand": "deepseek",
                "tier": "cheap",
                "popularity": 2,
                "pricing": {"prompt_1m": 0.27, "completion_1m": 1.10}
            }
        ],
        "vx_models": [
            {
                "id": "vertex_ai/gemini-2.5-pro",
                "name": "Gemini 2.5 Pro",
                "brand": "google",
                "tier": "frontier",
                "popularity": 10,
                "pricing": {"prompt_1m": 1.25, "completion_1m": 3.75}
            }
        ]
    }
    set_app_state_ref(mock_state)

@pytest.mark.asyncio
async def test_list_available_models_filter():
    # Filter by tier
    frontier = await list_available_models(tier="frontier")
    assert len(frontier) == 2
    assert all(m["tier"] == "frontier" for m in frontier)

    # Filter by provider
    vertex = await list_available_models(provider="vertex_ai")
    assert len(vertex) == 1
    assert vertex[0]["id"] == "vertex_ai/gemini-2.5-pro"

    # Filter by search
    deepseek = await list_available_models(search="deepseek")
    assert len(deepseek) == 1
    assert "deepseek" in deepseek[0]["id"]

@pytest.mark.asyncio
async def test_get_trending_models():
    trending = await get_trending_models()
    assert "frontier" in trending
    assert "cheap" in trending
    assert len(trending["frontier"]) >= 1
    assert len(trending["cheap"]) >= 1

@pytest.mark.asyncio
async def test_probe_model_tool():
    with patch("app.mcp_server.probe_model", new_callable=AsyncMock) as mock_probe:
        mock_probe.return_value = {"healthy": True, "latency_ms": 110.0, "response": "ok"}
        res = await mcp_test_model("openrouter/deepseek/deepseek-chat")
        assert res["healthy"] is True
        assert res["latency_ms"] == 110.0

@pytest.mark.asyncio
async def test_settings_tools():
    with patch("app.mcp_server.get_all_settings", new_callable=AsyncMock) as mock_get, \
         patch("app.mcp_server.set_setting", new_callable=AsyncMock) as mock_set:
        mock_get.return_value = {"APPRISE_URL": "http://apprise:8000/notify/system"}
        
        settings = await get_settings()
        assert settings["APPRISE_URL"] == "http://apprise:8000/notify/system"

        update_res = await update_settings({"NOTIFICATION_ENABLED": "true"})
        assert update_res["status"] == "success"
        mock_set.assert_called_once_with("NOTIFICATION_ENABLED", "true")

@pytest.mark.asyncio
async def test_send_test_notification_tool():
    with patch("app.mcp_server.send_notification", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "success", "status_code": 200}
        res = await send_test_notification()
        assert res["status"] == "success"
        mock_send.assert_called_once()

@pytest.mark.asyncio
async def test_add_and_remove_model_tools():
    with patch("app.mcp_server.list_active_models", new_callable=AsyncMock) as mock_active, \
         patch("app.mcp_server.sync_models", new_callable=AsyncMock) as mock_sync:
        
        mock_active.return_value = [
            {"litellm_params": {"model": "openrouter/deepseek/deepseek-chat"}, "model_name": "deepseek-chat"}
        ]
        mock_sync.return_value = {"status": "success", "updated_models": 2}
        
        # Test add model
        res = await add_model("vertex_ai/gemini-2.5-pro")
        assert res["status"] == "success"
        mock_sync.assert_called_once_with(["openrouter/deepseek/deepseek-chat", "vertex_ai/gemini-2.5-pro"])
        
        # Test remove model
        mock_sync.reset_mock()
        mock_sync.return_value = {"status": "success", "updated_models": 0}
        res_remove = await remove_model("openrouter/deepseek/deepseek-chat")
        assert res_remove["status"] == "success"
        mock_sync.assert_called_once_with([])

@pytest.mark.asyncio
async def test_sync_librechat_tool():
    with patch("app.mcp_server.get_all_settings", new_callable=AsyncMock) as mock_get_settings, \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", MagicMock()), \
         patch("yaml.safe_load", return_value={"model_list": [{"model_name": "vertex/gemini-3.7-flash"}]}), \
         patch("app.sync.export_librechat_config", return_value={"status": "success", "synced": [{"path": "p", "models_count": 1}]}) as mock_export:
        
        mock_get_settings.return_value = {"LITELLM_CONFIG": "/app/config/config.yaml"}
        res = await sync_librechat()
        assert res["status"] == "success"
        mock_export.assert_called_once()
