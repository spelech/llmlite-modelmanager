import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.capabilities import extract_benchmarks, resolve_benchmarks_for_model, FALLBACK_GEMINI_BENCHMARKS
from app.openrouter import get_openrouter_models
from app.sync import sync_models_internal
from app.mcp_server import list_available_models, set_app_state_ref

def test_extract_benchmarks_valid():
    raw_benchmarks = {
        "design_arena": [{"category": "codecategories", "elo": 1328}],
        "artificial_analysis": {
            "intelligence_index": 57.5,
            "coding_index": 71.5,
            "agentic_index": 58.2
        }
    }
    b = extract_benchmarks(raw_benchmarks)
    assert b["coding"] == 71.5
    assert b["intelligence"] == 57.5
    assert b["agentic"] == 58.2

def test_extract_benchmarks_empty_or_malformed():
    empty_expected = {"coding": None, "intelligence": None, "agentic": None}
    assert extract_benchmarks(None) == empty_expected
    assert extract_benchmarks({}) == empty_expected
    assert extract_benchmarks({"artificial_analysis": None}) == empty_expected
    assert extract_benchmarks({"artificial_analysis": {"coding_index": "invalid"}}) == empty_expected

def test_resolve_benchmarks_for_model_cross_reference():
    or_models = [
        {
            "id": "openrouter/google/gemini-3.7-flash",
            "benchmarks": {"coding": 76.1, "intelligence": 56.0, "agentic": 45.1}
        },
        {
            "id": "openrouter/qwen/qwen3.8-27b",
            "benchmarks": {"coding": 68.1, "intelligence": 52.0, "agentic": 50.9}
        }
    ]
    # Direct match from openrouter
    res = resolve_benchmarks_for_model("vertex_ai/gemini-3.7-flash", or_models)
    assert res["coding"] == 76.1
    assert res["intelligence"] == 56.0
    assert res["agentic"] == 45.1

def test_resolve_benchmarks_for_model_fallback():
    # Model not in or_models, should hit fallback
    res = resolve_benchmarks_for_model("vertex_ai/gemini-2.5-pro", [])
    assert res["coding"] == FALLBACK_GEMINI_BENCHMARKS["gemini-2.5-pro"]["coding"]
    assert res["intelligence"] == FALLBACK_GEMINI_BENCHMARKS["gemini-2.5-pro"]["intelligence"]

@pytest.mark.asyncio
async def test_mcp_list_available_models_benchmark_filters():
    mock_state = {
        "or_models": [
            {
                "id": "openrouter/qwen/qwen-2.5-coder-32b",
                "name": "Qwen 2.5 Coder 32B",
                "brand": "qwen",
                "tier": "moderate",
                "benchmarks": {"coding": 78.0, "intelligence": 55.0, "agentic": 50.0}
            },
            {
                "id": "openrouter/meta-llama/llama-3.1-8b",
                "name": "Llama 3.1 8B",
                "brand": "meta-llama",
                "tier": "cheap",
                "benchmarks": {"coding": 48.0, "intelligence": 45.0, "agentic": 35.0}
            },
            {
                "id": "openrouter/niche/unrated-model",
                "name": "Unrated Niche Model",
                "brand": "niche",
                "tier": "cheap",
                "benchmarks": {}
            }
        ],
        "vx_models": [
            {
                "id": "vertex_ai/gemini-3.7-flash",
                "name": "Gemini 3.7 Flash",
                "brand": "google",
                "tier": "cheap",
                "benchmarks": {"coding": 76.1, "intelligence": 56.0, "agentic": 45.1}
            }
        ]
    }
    set_app_state_ref(mock_state)

    # Filter min_coding_score >= 70
    coding_models = await list_available_models(min_coding_score=70.0)
    ids = [m["id"] for m in coding_models]
    assert "openrouter/qwen/qwen-2.5-coder-32b" in ids
    assert "vertex_ai/gemini-3.7-flash" in ids
    assert "openrouter/meta-llama/llama-3.1-8b" not in ids
    assert "openrouter/niche/unrated-model" not in ids

    # Filter min_intelligence_score >= 50
    intel_models = await list_available_models(min_intelligence_score=50.0)
    intel_ids = [m["id"] for m in intel_models]
    assert "openrouter/qwen/qwen-2.5-coder-32b" in intel_ids
    assert "vertex_ai/gemini-3.7-flash" in intel_ids
    assert "openrouter/meta-llama/llama-3.1-8b" not in intel_ids

@pytest.mark.asyncio
async def test_sync_models_includes_benchmarks(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("model_list: []\n")

    mock_state = {
        "or_models": [
            {
                "id": "openrouter/qwen/qwen-2.5-coder-32b",
                "name": "Qwen 2.5 Coder 32B",
                "brand": "qwen",
                "tier": "moderate",
                "pricing": {"prompt": 0.0000005, "completion": 0.000001},
                "max_input_tokens": 128000,
                "max_output_tokens": 8192,
                "capabilities": {"function_calling": True},
                "benchmarks": {"coding": 78.0, "intelligence": 55.0, "agentic": 50.0}
            }
        ],
        "vx_models": []
    }

    with patch("app.sync.get_app_setting", return_value=str(config_file)), \
         patch("app.sync.app_state", mock_state), \
         patch("app.sync.export_opencode_config"), \
         patch("app.sync.export_librechat_config", return_value={"status": "skipped"}):
        
        res = await sync_models_internal(["openrouter/qwen/qwen-2.5-coder-32b"])
        assert res["status"] == "success"

        import yaml
        with open(config_file, "r") as f:
            written_cfg = yaml.safe_load(f)
        
        m_info = written_cfg["model_list"][0]["model_info"]
        assert "benchmarks" in m_info
        assert m_info["benchmarks"]["coding"] == 78.0
        assert m_info["tier"] == "moderate"
