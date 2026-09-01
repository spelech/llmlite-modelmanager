import pytest
import yaml
from unittest.mock import patch, MagicMock
from app.sync import sync_models_internal
from app.config import app_state

@pytest.mark.asyncio
async def test_sync_disambiguates_duplicate_model_names(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("model_list: []")
    
    app_state["or_models"] = [
        {"id": "openrouter/google/gemini-3.7-flash", "name": "Gemini 3.7 Flash", "pricing": {"prompt": 0.0, "completion": 0.0}}
    ]
    app_state["vx_models"] = [
        {"id": "vertex_ai/gemini-3.7-flash", "name": "Gemini 3.7 Flash", "pricing": {"prompt": 0.0, "completion": 0.0}}
    ]
    
    with patch("app.sync.get_app_setting", return_value=str(config_file)), \
         patch("app.sync.export_opencode_config", return_value=None):
        res = await sync_models_internal([
            "openrouter/google/gemini-3.7-flash",
            "vertex_ai/gemini-3.7-flash"
        ])
        assert res["status"] == "success"
        assert res["updated_models"] == 2
        
        saved_cfg = yaml.safe_load(config_file.read_text())
        model_names = [m["model_name"] for m in saved_cfg["model_list"]]
        
        # Verify no duplicate model_names exist
        assert len(model_names) == len(set(model_names))
        assert "openrouter/gemini-3.7-flash" in model_names
        assert "vertex/gemini-3.7-flash" in model_names

@pytest.mark.asyncio
async def test_sync_single_provider_uses_clean_alias(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("model_list: []")
    
    app_state["or_models"] = [
        {"id": "openrouter/deepseek/deepseek-chat", "name": "DeepSeek V3", "pricing": {"prompt": 0.0, "completion": 0.0}}
    ]
    app_state["vx_models"] = [
        {"id": "vertex_ai/gemini-3.7-flash", "name": "Gemini 3.7 Flash", "pricing": {"prompt": 0.0, "completion": 0.0}}
    ]
    
    with patch("app.sync.get_app_setting", return_value=str(config_file)), \
         patch("app.sync.export_opencode_config", return_value=None):
        res = await sync_models_internal([
            "openrouter/deepseek/deepseek-chat",
            "vertex_ai/gemini-3.7-flash"
        ])
        assert res["status"] == "success"
        
        saved_cfg = yaml.safe_load(config_file.read_text())
        model_names = [m["model_name"] for m in saved_cfg["model_list"]]
        
        assert "deepseek-chat" in model_names
        assert "gemini-3.7-flash" in model_names


@pytest.mark.asyncio
async def test_sync_local_models_and_collision_disambiguation(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("model_list: []")
    
    app_state["or_models"] = [
        {"id": "openrouter/qwen/qwen3.5:9b", "name": "Qwen 3.5 9B", "pricing": {"prompt": 0.0000001, "completion": 0.0000002}}
    ]
    app_state["vx_models"] = []
    app_state["local_models"] = [
        {
            "id": "local/qwen3.5:9b",
            "name": "Qwen 3.5 9B (Local)",
            "brand": "ollama",
            "engine": "ollama",
            "tier": "cheap",
            "pricing": {"prompt": 0.0, "completion": 0.0},
            "max_input_tokens": 32768,
            "max_output_tokens": 8192,
            "capabilities": {"text_in": True, "text_out": True}
        },
        {
            "id": "local/deepseek-r1:14b",
            "name": "DeepSeek R1 14B",
            "brand": "ollama",
            "engine": "vllm",
            "tier": "cheap",
            "pricing": {"prompt": 0.0, "completion": 0.0},
            "max_input_tokens": 65536,
            "max_output_tokens": 8192,
            "capabilities": {"text_in": True, "text_out": True}
        }
    ]
    
    with patch("app.sync.get_app_setting", side_effect=lambda key, default=None: str(config_file) if key == "LITELLM_CONFIG" else default), \
         patch("app.sync.export_opencode_config", return_value=None):
        res = await sync_models_internal([
            "openrouter/qwen/qwen3.5:9b",
            "local/qwen3.5:9b",
            "local/deepseek-r1:14b"
        ])
        assert res["status"] == "success"
        assert res["updated_models"] == 3
        
        saved_cfg = yaml.safe_load(config_file.read_text())
        model_map_saved = {m["model_name"]: m for m in saved_cfg["model_list"]}
        
        # Check collision disambiguation
        assert "openrouter/qwen3.5:9b" in model_map_saved
        assert "local/qwen3.5:9b" in model_map_saved
        # Unique local model uses clean base name
        assert "deepseek-r1:14b" in model_map_saved
        
        # Check ollama engine litellm_params and model_info
        local_qwen = model_map_saved["local/qwen3.5:9b"]
        assert local_qwen["litellm_params"]["model"] == "ollama_chat/qwen3.5:9b"
        assert local_qwen["litellm_params"]["api_base"] == "http://10.0.0.21:5246"
        assert local_qwen["model_info"]["input_cost_per_token"] == 0.0
        assert local_qwen["model_info"]["output_cost_per_token"] == 0.0
        assert local_qwen["model_info"]["max_input_tokens"] == 32768
        assert local_qwen["model_info"]["tier"] == "cheap"
        assert local_qwen["model_info"]["brand"] == "ollama"
        
        # Check vllm/openai engine litellm_params
        local_ds = model_map_saved["deepseek-r1:14b"]
        assert local_ds["litellm_params"]["model"] == "openai/deepseek-r1:14b"
        assert local_ds["litellm_params"]["api_base"] == "http://10.0.0.21:5246/v1"
        assert local_ds["model_info"]["max_input_tokens"] == 65536

@pytest.mark.asyncio
async def test_sync_removeprefix_local_handling(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("model_list: []")
    
    app_state["or_models"] = []
    app_state["vx_models"] = []
    app_state["local_models"] = [
        {
            "id": "local/qwen2.5-coder:7b",
            "name": "qwen2.5-coder:7b",
            "brand": "ollama",
            "engine": "ollama",
            "tier": "cheap",
            "pricing": {"prompt": 0.0, "completion": 0.0},
            "max_input_tokens": 131072,
            "max_output_tokens": 8192,
            "capabilities": {"text_in": True, "text_out": True}
        }
    ]
    
    with patch("app.sync.get_app_setting", side_effect=lambda key, default=None: str(config_file) if key == "LITELLM_CONFIG" else default), \
         patch("app.sync.export_opencode_config", return_value=None):
        res = await sync_models_internal(["local/qwen2.5-coder:7b"])
        assert res["status"] == "success"
        
        saved_cfg = yaml.safe_load(config_file.read_text())
        model = saved_cfg["model_list"][0]
        assert model["model_name"] == "qwen2.5-coder:7b"
        assert model["litellm_params"]["model"] == "ollama_chat/qwen2.5-coder:7b"
        assert model["model_info"]["id"] == "local/qwen2.5-coder:7b"


