import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.health import probe_model, check_active_models_health

@pytest.mark.asyncio
async def test_probe_model_catalog_openrouter():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"id": "deepseek/deepseek-chat", "name": "DeepSeek V3"}}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await probe_model("openrouter/deepseek/deepseek-chat", settings={}, mode="catalog")
        assert res["healthy"] is True
        assert "0 Tokens" in res["response"]
        assert res["error"] is None

@pytest.mark.asyncio
async def test_probe_model_live_openrouter():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "pong"}}]}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await probe_model("openrouter/deepseek/deepseek-chat", settings={"OPENROUTER_API_KEY": "test-key"}, mode="live")
        assert res["healthy"] is True
        assert res["response"] == "pong"
        assert res["error"] is None

@pytest.mark.asyncio
async def test_probe_model_openrouter_failure():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Model not found"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await probe_model("openrouter/deepseek/deepseek-chat", settings={}, mode="catalog")
        assert res["healthy"] is False
        assert "404" in res["error"]

@pytest.mark.asyncio
async def test_check_active_models_health(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
model_list:
  - model_name: claude-3-5-sonnet
    litellm_params:
      model: openrouter/anthropic/claude-3-5-sonnet
  - model_name: gemini-2-5-flash
    litellm_params:
      model: vertex_ai/gemini-2.5-flash
""")

    with patch("app.health.probe_model", new_callable=AsyncMock) as mock_probe, \
         patch("app.health.update_model_health", new_callable=AsyncMock), \
         patch("app.health.notify_model_unavailable", new_callable=AsyncMock) as mock_notify:
        
        # 1 healthy, 1 unhealthy
        mock_probe.side_effect = [
            {"healthy": True, "latency_ms": 120.0, "response": "ok", "error": None},
            {"healthy": False, "latency_ms": 50.0, "response": None, "error": "Model deprecated"}
        ]
        
        res = await check_active_models_health(config_path=str(config_file), notify=True)
        assert res["status"] == "success"
        assert res["total_checked"] == 2
        assert res["healthy"] == 1
        assert res["unhealthy"] == 1
        assert res["mode"] == "catalog"
        mock_notify.assert_called_once_with("vertex_ai/gemini-2.5-flash", "Model deprecated")
