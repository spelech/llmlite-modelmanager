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
        assert local_qwen["model_info"]["pricing_tier"] == "cheap"
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

@pytest.mark.asyncio
async def test_sync_dynamic_router_sanitizes_cost_per_token(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("model_list: []")

    app_state["or_models"] = [
        {
            "id": "openrouter/typesafe/jev-router",
            "name": "TypeSafe: Jev Router",
            "brand": "typesafe",
            "tier": "moderate",
            "pricing": {
                "prompt": -1.0,
                "completion": -1.0,
                "prompt_1m": -1000000.0,
                "completion_1m": -1000000.0,
                "is_dynamic_router": True
            },
            "max_input_tokens": 128000,
            "max_output_tokens": 8192
        }
    ]
    app_state["vx_models"] = []
    app_state["local_models"] = []

    with patch("app.sync.get_app_setting", side_effect=lambda key, default=None: str(config_file) if key == "LITELLM_CONFIG" else default), \
         patch("app.sync.export_opencode_config", return_value=None):
        res = await sync_models_internal(["openrouter/typesafe/jev-router"])
        assert res["status"] == "success"

        saved_cfg = yaml.safe_load(config_file.read_text())
        model = saved_cfg["model_list"][0]
        assert model["model_name"] == "jev-router"
        assert model["litellm_params"]["model"] == "openrouter/typesafe/jev-router"
        # Zeroed cost per token to prevent -$10K bug
        assert model["model_info"]["input_cost_per_token"] == 0.0
        assert model["model_info"]["output_cost_per_token"] == 0.0


@pytest.mark.asyncio
async def test_sync_preserves_custom_agy_models_and_prunes_removed_from_opencode(tmp_path):
    import json
    config_file = tmp_path / "config.yaml"
    opencode_file = tmp_path / "opencode.jsonc"

    initial_cfg = {
        "router_settings": {
            "model_group_alias": {
                "opencode-default": "glm-5.3",
                "glm": "glm-5.3"
            }
        },
        "model_list": [
            {
                "model_name": "agy-argon-xhigh",
                "litellm_params": {
                    "model": "openai/agy-argon-xhigh",
                    "api_base": "http://10.0.0.10:8032/v1",
                    "api_key": "not-needed"
                },
                "model_info": {
                    "id": "openai/agy-argon-xhigh",
                    "max_input_tokens": 1048576,
                    "max_output_tokens": 65536,
                    "brand": "google",
                    "pricing_tier": "free"
                }
            },
            {
                "model_name": "old-removed-model",
                "litellm_params": {"model": "openrouter/z-ai/glm-5.1"},
                "model_info": {"id": "openrouter/z-ai/glm-5.1", "max_input_tokens": 204800, "max_output_tokens": 8192}
            }
        ]
    }
    config_file.write_text(yaml.safe_dump(initial_cfg))

    opencode_file.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "providers": {
            "litellm": {
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {"baseURL": "http://10.0.0.10:8448/v1"},
                "models": {
                    "opencode-default": {"name": "opencode-default", "limit": {"context": 1000000, "output": 65536}},
                    "agy-argon-xhigh": {"name": "agy-argon-xhigh", "limit": {"context": 1048576, "output": 65536}},
                    "old-removed-model": {"name": "old-removed-model", "limit": {"context": 204800, "output": 8192}}
                }
            }
        }
    }))

    app_state["or_models"] = [
        {
            "id": "openrouter/z-ai/glm-5.3",
            "name": "GLM 5.3",
            "brand": "z-ai",
            "tier": "moderate",
            "pricing": {"prompt": 0.0000014, "completion": 0.0000044},
            "max_input_tokens": 1048576,
            "max_output_tokens": 65536
        }
    ]
    app_state["vx_models"] = []
    app_state["local_models"] = []

    from app.sync import export_opencode_config as real_export_opencode
    with patch("app.sync.get_app_setting", side_effect=lambda key, default=None: str(config_file) if key == "LITELLM_CONFIG" else default), \
         patch("app.sync.export_opencode_config", side_effect=lambda models, **kw: real_export_opencode(models, target_path=str(opencode_file), **kw)):
        res = await sync_models_internal(["openrouter/z-ai/glm-5.3"])
        assert res["status"] == "success"
        assert res["updated_models"] == 1
        assert res["preserved_custom_models"] == 1

        saved_cfg = yaml.safe_load(config_file.read_text())
        names = [m["model_name"] for m in saved_cfg["model_list"]]
        assert names == ["agy-argon-xhigh", "glm-5.3"]
        assert saved_cfg["model_list"][0]["litellm_params"]["api_base"] == "http://10.0.0.10:8032/v1"
        assert saved_cfg["router_settings"]["model_group_alias"]["glm"] == "glm-5.3"

        oc_data = json.loads(opencode_file.read_text())
        oc_models = oc_data["providers"]["litellm"]["models"]
        assert "opencode-default" in oc_models
        assert "glm" in oc_models
        assert oc_models["glm"]["limit"]["context"] == 1048576
        assert "glm-5.3" not in oc_models
        assert "old-removed-model" not in oc_models


def test_build_model_group_aliases_resolves_clean_family_aliases():
    from app.aliases import build_model_group_aliases
    model_list = [
        {"model_name": "gemini-3.8-flash", "model_info": {"id": "vertex_ai/gemini-3.8-flash"}},
        {"model_name": "gemini-3.5-flash-lite", "model_info": {"id": "vertex_ai/gemini-3.5-flash-lite"}},
        {"model_name": "gemini-4-argon", "model_info": {"id": "vertex_ai/gemini-4-argon"}},
        {"model_name": "glm-5.3", "model_info": {"id": "openrouter/z-ai/glm-5.3"}},
        {"model_name": "glm-5.3-flash", "model_info": {"id": "openrouter/z-ai/glm-5.3-flash"}},
        {"model_name": "deepseek-v4-pro", "model_info": {"id": "openrouter/deepseek/deepseek-v4-pro"}},
        {"model_name": "deepseek-v4.1-flash", "model_info": {"id": "openrouter/deepseek/deepseek-v4.1-flash"}},
        {"model_name": "qwen3.8-flash", "model_info": {"id": "openrouter/qwen/qwen3.8-flash"}},
        {"model_name": "qwen3.8-max", "model_info": {"id": "openrouter/qwen/qwen3.8-max"}},
        {"model_name": "qwen3.8-27b", "model_info": {"id": "openrouter/qwen/qwen3.8-27b"}},
        {"model_name": "hy4-preview", "model_info": {"id": "openrouter/tencent/hy4-preview"}},
        {"model_name": "hy3", "model_info": {"id": "openrouter/tencent/hy3"}},
        {"model_name": "jev-router", "model_info": {"id": "openrouter/typesafe/jev-router"}},
    ]
    aliases = build_model_group_aliases(model_list)
    assert aliases == {
        "opencode-default": "gemini-3.8-flash",
        "flash-latest": "gemini-3.8-flash",
        "opencode-small": "gemini-3.5-flash-lite",
        "flash-lite-latest": "gemini-3.5-flash-lite",
        "argon": "gemini-4-argon",
        "glm": "glm-5.3",
        "glm-flash": "glm-5.3-flash",
        "deepseek-pro": "deepseek-v4-pro",
        "deepseek-flash": "deepseek-v4.1-flash",
        "qwen-flash": "qwen3.8-flash",
        "qwen-max": "qwen3.8-max",
        "qwen-cheap": "qwen3.8-27b",
        "hy4": "hy4-preview",
        "hy3": "hy3",
        "jev-router": "jev-router",
    }


@pytest.mark.asyncio
async def test_sync_vertex_uses_token_not_character_pricing(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("model_list: []")
    app_state["or_models"] = []
    app_state["vx_models"] = [
        {
            "id": "vertex_ai/gemini-3.8-flash",
            "name": "Gemini 3.8 Flash",
            "brand": "google",
            "tier": "moderate",
            "pricing": {"prompt": 0.0000015, "completion": 0.0000075},
            "max_input_tokens": 1000000,
            "max_output_tokens": 65536,
            "capabilities": {"text_in": True, "text_out": True},
        }
    ]
    app_state["local_models"] = []
    with patch("app.sync.get_app_setting", side_effect=lambda k, d=None: str(config_file) if k == "LITELLM_CONFIG" else d), \
         patch("app.sync.export_opencode_config", return_value=None), \
         patch("app.sync.export_remote_opencode_config", return_value=[]):
        await sync_models_internal(["vertex_ai/gemini-3.8-flash"])
        saved_cfg = yaml.safe_load(config_file.read_text())
        mi = saved_cfg["model_list"][0]["model_info"]
        assert mi["input_cost_per_token"] == 0.0000015
        assert mi["output_cost_per_token"] == 0.0000075
        assert mi["cache_read_input_token_cost"] == 0.00000015
        assert mi["output_cost_per_reasoning_token"] == 0.0000075
        assert "input_cost_per_character" not in mi
        assert "output_cost_per_character" not in mi






