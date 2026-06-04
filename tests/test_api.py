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

@patch("main.requests.get")
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
    assert "Qwen 3.7 Plus" in response.text
    assert "Gemini 3.5 Flash" in response.text

@patch("main.requests.post")
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
         patch("main.get_vertex_models", return_value=[]), \
         patch("builtins.open", MagicMock()), \
         patch("yaml.safe_load", return_value={"model_list": []}), \
         patch("yaml.safe_dump") as mock_dump:
        
        response = client.post("/sync", data={"models": ["openrouter/a"]})
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert response.json()["updated_models"] == 1
