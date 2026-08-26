import pytest
from unittest.mock import patch, AsyncMock
from app.discovery import classify_model_tier, process_and_track_discovered_models

def test_classify_model_tier():
    # Cheap (<= $0.30 per 1M)
    cheap_model = {
        "id": "openrouter/google/gemini-2.5-flash",
        "name": "Gemini 2.5 Flash",
        "pricing": {"prompt_1m": 0.10, "completion_1m": 0.40}
    }
    assert classify_model_tier(cheap_model) == "cheap"

    # Moderate ($0.30 - $2.50 per 1M)
    moderate_model = {
        "id": "openrouter/meta-llama/llama-3.3-70b-instruct",
        "name": "Llama 3.3 70B Instruct",
        "pricing": {"prompt_1m": 0.70, "completion_1m": 0.80}
    }
    assert classify_model_tier(moderate_model) == "moderate"

    # Frontier (> $2.50 per 1M)
    frontier_model = {
        "id": "openrouter/anthropic/claude-3.5-sonnet",
        "name": "Claude 3.5 Sonnet",
        "pricing": {"prompt_1m": 3.00, "completion_1m": 15.00}
    }
    assert classify_model_tier(frontier_model) == "frontier"

    # Keyword fallback for zero pricing
    deepseek_r1 = {
        "id": "openrouter/deepseek/deepseek-r1",
        "name": "DeepSeek R1",
        "pricing": {"prompt_1m": 0.0, "completion_1m": 0.0}
    }
    assert classify_model_tier(deepseek_r1) == "frontier"

    gemini_lite = {
        "id": "vertex_ai/gemini-3.1-flash-lite",
        "name": "Gemini 3.1 Flash Lite",
        "pricing": {"prompt_1m": 0.0, "completion_1m": 0.0}
    }
    assert classify_model_tier(gemini_lite) == "cheap"

@pytest.mark.asyncio
async def test_process_and_track_discovered_models():
    sample_models = [
        {
            "id": "openrouter/deepseek/deepseek-chat",
            "name": "DeepSeek V3",
            "brand": "deepseek",
            "pricing": {"prompt_1m": 0.27, "completion_1m": 1.10},
            "popularity": 5
        }
    ]
    with patch("app.discovery.upsert_discovered_models", new_callable=AsyncMock) as mock_upsert, \
         patch("app.discovery.notify_new_trending_models", new_callable=AsyncMock) as mock_notify:
        mock_upsert.return_value = sample_models
        new_models = await process_and_track_discovered_models(sample_models, notify=True)
        assert len(new_models) == 1
        assert new_models[0]["tier"] == "cheap"
        mock_notify.assert_called_once()
