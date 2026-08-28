import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from main import app

client = TestClient(app)

@pytest.fixture
def mock_openrouter_resp():
    return {
        "data": [
            {
                "id": "qwen/qwen3.7-plus",
                "name": "Qwen 3.7 Plus",
                "pricing": {"prompt": "0.0000004", "completion": "0.0000016"},
                "context_length": 128000
            }
        ]
    }

@pytest.fixture
def mock_google_billing_resp():
    return {
        "skus": [
            {
                "description": "Gemini 3.5 Flash Global Text Input - Predictions",
                "serviceRegions": ["global"],
                "pricingInfo": [{
                    "pricingExpression": {
                        "tieredRates": [{"unitPrice": {"units": 0, "nanos": 1500}}],
                        "usageUnitDescription": "count"
                    }
                }]
            }
        ]
    }

@patch("httpx.AsyncClient.get")
@patch("main.get_google_access_token")
def test_index(mock_token, mock_get, mock_openrouter_resp, mock_google_billing_resp):
    # Mock OpenRouter
    mock_or = MagicMock()
    mock_or.status_code = 200
    mock_or.json.return_value = mock_openrouter_resp
    
    # Mock Google Billing
    mock_vx = MagicMock()
    mock_vx.status_code = 200
    mock_vx.json.return_value = mock_google_billing_resp
    
    mock_get.side_effect = [mock_or, mock_vx]
    mock_token.return_value = "fake-token"
    
    response = client.get("/")
    assert response.status_code == 200

@patch("httpx.AsyncClient.post")
def test_test_model_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "Pong!"}}]
    }
    mock_post.return_value = mock_resp
    
    response = client.post("/test", data={"model_id": "openrouter/deepseek/deepseek-chat"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["response"] == "Pong!"

def test_sync_models_minimal():
    # We mock the entire logic of file writing for sync
    with patch("main.get_openrouter_models", return_value=[{"id": "openrouter/a", "name": "A"}]), \
         patch("main.verify_and_cache_vertex_models", return_value=None), \
         patch("main.export_opencode_config", return_value=None), \
         patch("builtins.open", MagicMock()), \
         patch("yaml.safe_load", return_value={"model_list": []}), \
         patch("yaml.safe_dump") as mock_dump:
        
        response = client.post("/sync", data={"models": ["openrouter/a"]})
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert response.json()["updated_models"] == 1

def test_api_models_discovered():
    response = client.get("/api/models/discovered")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_api_notifications_test():
    with patch("main.send_notification", return_value={"status": "success", "status_code": 200}):
        response = client.post("/api/notifications/test", json={"url": "http://apprise:8000/notify/system"})
        assert response.status_code == 200
        assert response.json()["status"] == "success"

def test_api_health_check():
    with patch("main.check_active_models_health", return_value={"status": "success", "total_checked": 0, "healthy": 0, "unhealthy": 0, "results": []}):
        response = client.post("/api/health/check")
        assert response.status_code == 200
        assert response.json()["status"] == "success"

def test_api_sync_librechat():
    with patch("main.export_librechat_config", return_value={"status": "success", "synced": [{"path": "dummy", "models_count": 1}]}), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", MagicMock()):
        with patch("yaml.safe_load", return_value={"model_list": [{"model_name": "test"}]}):
            response = client.post("/api/sync/librechat")
            assert response.status_code == 200
            assert response.json()["status"] == "success"
            assert response.json()["exported_models"] == 1

def test_restart_litellm_success():
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_docker.containers.get.return_value = mock_container
    
    with patch("docker.from_env", return_value=mock_docker), \
         patch("app.sync.verify_litellm_healthy", return_value=True):
        response = client.post("/restart-litellm")
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_container.restart.assert_called_once()

def test_restart_litellm_failure_and_auto_revert():
    mock_docker = MagicMock()
    mock_container = MagicMock()
    mock_docker.containers.get.return_value = mock_container
    
    with patch("docker.from_env", return_value=mock_docker), \
         patch("app.sync.verify_litellm_healthy", return_value=False), \
         patch("os.path.exists", return_value=True), \
         patch("shutil.copy2") as mock_copy, \
         patch("app.sync.send_notification", return_value=None):
        response = client.post("/restart-litellm")
        assert response.status_code == 200
        assert response.json()["status"] == "error"
        assert response.json()["reverted"] is True
        mock_copy.assert_called_once()
        assert mock_container.restart.call_count == 2

@pytest.mark.asyncio
async def test_verify_litellm_healthy_direct_execution():
    from app.sync import verify_litellm_healthy
    with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
        healthy = await verify_litellm_healthy(timeout=0.1)
        assert healthy is False

