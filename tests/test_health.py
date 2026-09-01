import pytest
import httpx
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

@pytest.mark.asyncio
async def test_probe_model_catalog_local_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [
            {"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b"}
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await probe_model("local/qwen2.5-coder:7b", settings={"LOCAL_LLM_URL": "http://10.0.0.21:5246"}, mode="catalog")
        assert res["healthy"] is True
        assert res["response"] == "Catalog Active (qwen2.5-coder:7b) [0 Tokens]"
        assert res["error"] is None

@pytest.mark.asyncio
async def test_probe_model_catalog_local_not_found():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [
            {"name": "llama3:8b", "model": "llama3:8b"}
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await probe_model("local/qwen2.5-coder:7b", settings={}, mode="catalog")
        assert res["healthy"] is False
        assert "not found" in res["error"].lower()

@pytest.mark.asyncio
async def test_probe_model_catalog_local_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await probe_model("local/qwen2.5-coder:7b", settings={}, mode="catalog")
        assert res["healthy"] is False
        assert "500" in res["error"]

@pytest.mark.asyncio
async def test_probe_model_catalog_local_network_error():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        res = await probe_model("local/qwen2.5-coder:7b", settings={}, mode="catalog")
        assert res["healthy"] is False
        assert "Connection refused" in res["error"]

@pytest.mark.asyncio
async def test_probe_model_live_local_v1_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "1"}}]}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await probe_model("local/qwen2.5-coder:7b", settings={"LOCAL_LLM_URL": "http://10.0.0.21:5246"}, mode="live")
        assert res["healthy"] is True
        assert res["response"] == "1"
        assert res["error"] is None

@pytest.mark.asyncio
async def test_probe_model_live_local_fallback_api_chat_success():
    mock_resp_404 = MagicMock()
    mock_resp_404.status_code = 404
    mock_resp_404.text = "Not Found"

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {"message": {"content": "1"}}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [mock_resp_404, mock_resp_200]
        res = await probe_model("local/qwen2.5-coder:7b", settings={}, mode="live")
        assert res["healthy"] is True
        assert res["response"] == "1"
        assert res["error"] is None
        assert mock_post.call_count == 2

@pytest.mark.asyncio
async def test_probe_model_live_local_failure():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Engine error"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await probe_model("local/qwen2.5-coder:7b", settings={}, mode="live")
        assert res["healthy"] is False
        assert "500" in res["error"]

@pytest.mark.asyncio
async def test_probe_model_live_local_network_error():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ConnectError("Connection failed")
        res = await probe_model("local/qwen2.5-coder:7b", settings={}, mode="live")
        assert res["healthy"] is False
        assert "Connection failed" in res["error"]

@pytest.mark.asyncio
async def test_check_active_models_health_with_local_model_info(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
model_list:
  - model_name: qwen3.5:9b
    litellm_params:
      model: ollama_chat/qwen3.5:9b
      api_base: http://10.0.0.21:5246
    model_info:
      id: local/qwen3.5:9b
  - model_name: claude-3-5-sonnet
    litellm_params:
      model: openrouter/anthropic/claude-3-5-sonnet
    model_info:
      id: openrouter/anthropic/claude-3-5-sonnet
""")

    with patch("app.health.probe_model", new_callable=AsyncMock) as mock_probe, \
         patch("app.health.update_model_health", new_callable=AsyncMock):
        
        mock_probe.return_value = {"healthy": True, "latency_ms": 50.0, "response": "ok", "error": None}
        
        res = await check_active_models_health(config_path=str(config_file), notify=False)
        assert res["status"] == "success"
        assert res["total_checked"] == 2
        assert res["healthy"] == 2
        
        # Verify probe_model was called with model_info.id ("local/qwen3.5:9b" and "openrouter/anthropic/claude-3-5-sonnet")
        probed_model_ids = [call.args[0] for call in mock_probe.call_args_list]
        assert "local/qwen3.5:9b" in probed_model_ids
        assert "openrouter/anthropic/claude-3-5-sonnet" in probed_model_ids

@pytest.mark.asyncio
async def test_probe_model_catalog_ollama_chat_and_ollama_prefixes():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [
            {"name": "qwen3.5:9b", "model": "qwen3.5:9b"}
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        
        # Test ollama_chat/ prefix
        res_chat = await probe_model("ollama_chat/qwen3.5:9b", settings={"LOCAL_LLM_URL": "http://10.0.0.21:5246"}, mode="catalog")
        assert res_chat["healthy"] is True
        assert res_chat["response"] == "Catalog Active (qwen3.5:9b) [0 Tokens]"
        
        # Test ollama/ prefix
        res_ollama = await probe_model("ollama/qwen3.5:9b", settings={"LOCAL_LLM_URL": "http://10.0.0.21:5246"}, mode="catalog")
        assert res_ollama["healthy"] is True
        assert res_ollama["response"] == "Catalog Active (qwen3.5:9b) [0 Tokens]"

@pytest.mark.asyncio
async def test_probe_model_live_ollama_chat_and_ollama_prefixes():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "pong"}}]}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        
        # Test ollama_chat/ prefix
        res_chat = await probe_model("ollama_chat/qwen3.5:9b", settings={"LOCAL_LLM_URL": "http://10.0.0.21:5246"}, mode="live")
        assert res_chat["healthy"] is True
        assert res_chat["response"] == "pong"
        
        # Test ollama/ prefix
        res_ollama = await probe_model("ollama/qwen3.5:9b", settings={"LOCAL_LLM_URL": "http://10.0.0.21:5246"}, mode="live")
        assert res_ollama["healthy"] is True
        assert res_ollama["response"] == "pong"

