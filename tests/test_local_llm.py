import os
import json
import time
import pytest
import httpx
from unittest.mock import patch, MagicMock, AsyncMock, mock_open

from app.local_llm import (
    fetch_local_models,
    verify_and_cache_local_models,
    map_local_capabilities,
    DEFAULT_LOCAL_LLM_URL,
    LOCAL_CACHE_FILE
)
from app.config import app_state

SAMPLE_L3M2_RESPONSE = {
    "models": [
        {
            "name": "qwen3.5:9b",
            "model": "qwen3.5:9b",
            "modified_at": "2026-07-30T23:49:26.6005477-05:00",
            "size": 6594474711,
            "digest": "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7",
            "details": {
                "parent_model": "",
                "format": "gguf",
                "family": "qwen35",
                "families": ["qwen35"],
                "parameter_size": "9.7B",
                "quantization_level": "Q4_K_M",
                "context_length": 262144,
                "embedding_length": 4096
            },
            "capabilities": ["vision", "completion", "tools", "thinking"]
        },
        {
            "name": "qwen2.5-coder:1.5b",
            "model": "qwen2.5-coder:1.5b",
            "modified_at": "2026-07-30T01:04:47.3641751-05:00",
            "size": 986062089,
            "digest": "d7372fd828518a4d38b1eb196c673c31a85f2ed302b3d1e406c4c2d1b64a0668",
            "details": {
                "parent_model": "",
                "format": "gguf",
                "family": "qwen2",
                "families": ["qwen2"],
                "parameter_size": "1.5B",
                "quantization_level": "Q4_K_M",
                "context_length": 32768,
                "embedding_length": 1536
            },
            "capabilities": ["completion", "tools", "insert"]
        },
        {
            "name": "deepseek-r1:8b",
            "model": "deepseek-r1:8b",
            "modified_at": "2026-07-05T21:14:47.7762605-05:00",
            "size": 4920499875,
            "digest": "c1c301c090d0680844d9e9d6166bc788d95be2f6fab2b21134f11d70634cd1bf",
            "details": {
                "parent_model": "",
                "format": "gguf",
                "family": "deepseek2",
                "families": ["deepseek2"],
                "parameter_size": "8B",
                "quantization_level": "Q4_K_M"
            },
            "capabilities": ["completion", "thinking"]
        }
    ]
}

@pytest.mark.asyncio
async def test_fetch_local_models_normalization():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = SAMPLE_L3M2_RESPONSE

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        models = await fetch_local_models("http://10.0.0.21:5246")

        assert len(models) == 3
        model_by_id = {m["id"]: m for m in models}

        # Model 1: qwen3.5:9b (vision + tools + 262k context)
        assert "local/qwen3.5:9b" in model_by_id
        m1 = model_by_id["local/qwen3.5:9b"]
        assert m1["id"] == "local/qwen3.5:9b"
        assert m1["name"] == "qwen3.5:9b"
        assert m1["engine"] == "ollama"
        assert m1["brand"] == "ollama"
        assert m1["tier"] == "cheap"
        assert m1["pricing"]["prompt"] == 0.0
        assert m1["pricing"]["completion"] == 0.0
        assert m1["pricing"]["prompt_1m"] == 0.0
        assert m1["pricing"]["completion_1m"] == 0.0
        assert m1["max_input_tokens"] == 262144
        assert m1["max_output_tokens"] == 8192
        assert m1["capabilities"]["text_in"] is True
        assert m1["capabilities"]["text_out"] is True
        assert m1["capabilities"]["image_in"] is True
        assert m1["capabilities"]["function_calling"] is True
        assert m1["capabilities"]["streaming"] is True

        # Model 2: qwen2.5-coder:1.5b (no vision, has tools, 32k context)
        assert "local/qwen2.5-coder:1.5b" in model_by_id
        m2 = model_by_id["local/qwen2.5-coder:1.5b"]
        assert m2["id"] == "local/qwen2.5-coder:1.5b"
        assert m2["max_input_tokens"] == 32768
        assert m2["capabilities"]["image_in"] is False
        assert m2["capabilities"]["function_calling"] is True

        # Model 3: deepseek-r1:8b (no context_length specified -> default 131072, no tools)
        assert "local/deepseek-r1:8b" in model_by_id
        m3 = model_by_id["local/deepseek-r1:8b"]
        assert m3["id"] == "local/deepseek-r1:8b"
        assert m3["max_input_tokens"] == 131072
        assert m3["max_output_tokens"] == 8192
        assert m3["capabilities"]["image_in"] is False
        assert m3["capabilities"]["function_calling"] is False

@pytest.mark.asyncio
async def test_fetch_local_models_offline_error():
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
        models = await fetch_local_models("http://10.0.0.21:5246")
        assert models == []

@pytest.mark.asyncio
async def test_fetch_local_models_non_200():
    mock_response = MagicMock()
    mock_response.status_code = 500

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        models = await fetch_local_models("http://10.0.0.21:5246")
        assert models == []

def test_map_local_capabilities():
    caps_vision_tools = map_local_capabilities(["vision", "tools", "completion"])
    assert caps_vision_tools["text_in"] is True
    assert caps_vision_tools["text_out"] is True
    assert caps_vision_tools["image_in"] is True
    assert caps_vision_tools["function_calling"] is True
    assert caps_vision_tools["streaming"] is True

    caps_tools_only = map_local_capabilities(["tools"])
    assert caps_tools_only["image_in"] is False
    assert caps_tools_only["function_calling"] is True

    caps_empty = map_local_capabilities([])
    assert caps_empty["text_in"] is True
    assert caps_empty["text_out"] is True
    assert caps_empty["image_in"] is False
    assert caps_empty["function_calling"] is False
    assert caps_empty["streaming"] is True

@pytest.mark.asyncio
async def test_verify_and_cache_local_models_online():
    mock_fetched = [
        {
            "id": "local/qwen3.5:9b",
            "name": "qwen3.5:9b",
            "engine": "ollama",
            "brand": "ollama",
            "tier": "cheap",
            "pricing": {"prompt": 0.0, "completion": 0.0, "prompt_1m": 0.0, "completion_1m": 0.0},
            "max_input_tokens": 262144,
            "max_output_tokens": 8192,
            "capabilities": {"text_in": True, "text_out": True, "image_in": True, "image_out": False, "audio_in": False, "audio_out": False, "video_in": False, "video_out": False, "pdf_in": False, "function_calling": True, "streaming": True}
        }
    ]

    with patch("app.local_llm.fetch_local_models", new_callable=AsyncMock, return_value=mock_fetched) as mock_fetch, \
         patch("app.local_llm.process_and_track_discovered_models", new_callable=AsyncMock) as mock_track, \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open()) as mock_file:
        
        models = await verify_and_cache_local_models()
        assert models == mock_fetched
        assert app_state["local_models"] == mock_fetched
        mock_track.assert_called_once()
        mock_file().write.assert_called()

@pytest.mark.asyncio
async def test_verify_and_cache_local_models_offline_uses_cache():
    cached_payload = {
        "timestamp": time.time() - 3600,  # 1 hour ago
        "models": [
            {
                "id": "local/qwen3.5:9b",
                "name": "qwen3.5:9b",
                "engine": "ollama",
                "brand": "ollama",
                "tier": "cheap",
                "pricing": {"prompt": 0.0, "completion": 0.0, "prompt_1m": 0.0, "completion_1m": 0.0},
                "max_input_tokens": 262144,
                "max_output_tokens": 8192,
                "capabilities": {"text_in": True, "text_out": True, "image_in": True, "image_out": False, "audio_in": False, "audio_out": False, "video_in": False, "video_out": False, "pdf_in": False, "function_calling": True, "streaming": True}
            }
        ]
    }

    with patch("app.local_llm.fetch_local_models", new_callable=AsyncMock, return_value=[]), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=json.dumps(cached_payload))):
        
        models = await verify_and_cache_local_models()
        assert len(models) == 1
        assert models[0]["id"] == "local/qwen3.5:9b"
        assert app_state["local_models"] == models

@pytest.mark.asyncio
async def test_verify_and_cache_local_models_expired_cache():
    cached_payload = {
        "timestamp": time.time() - (8 * 24 * 3600),  # 8 days ago (expired)
        "models": [
            {
                "id": "local/qwen3.5:9b",
                "name": "qwen3.5:9b",
                "engine": "ollama",
                "brand": "ollama",
                "tier": "cheap",
                "pricing": {"prompt": 0.0, "completion": 0.0, "prompt_1m": 0.0, "completion_1m": 0.0},
                "max_input_tokens": 262144,
                "max_output_tokens": 8192,
                "capabilities": {"text_in": True, "text_out": True, "image_in": True, "image_out": False, "audio_in": False, "audio_out": False, "video_in": False, "video_out": False, "pdf_in": False, "function_calling": True, "streaming": True}
            }
        ]
    }

    with patch("app.local_llm.fetch_local_models", new_callable=AsyncMock, return_value=[]), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=json.dumps(cached_payload))):
        
        models = await verify_and_cache_local_models()
        assert models == []
