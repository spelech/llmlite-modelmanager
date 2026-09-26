import pytest
from app.sync import normalize_opencode_v2_config

def test_normalize_fresh_config():
    models = [
        {"model_name": "claude-sonnet-4-5", "model_info": {"max_input_tokens": 200000, "max_output_tokens": 8192}}
    ]
    res = normalize_opencode_v2_config({}, models)
    assert res["$schema"] == "https://opencode.ai/config.json"
    assert "providers" in res
    assert "provider" not in res
    litellm = res["providers"]["litellm"]
    assert litellm["package"] == "@opencode/ai/providers/openai-compatible"
    assert litellm["settings"]["baseURL"] == "http://10.0.0.10:8448/v1"
    assert "options" not in litellm
    assert "npm" not in litellm
    assert "claude-sonnet-4-5" in litellm["models"]
    assert litellm["models"]["claude-sonnet-4-5"]["limit"]["context"] == 200000
    assert litellm["models"]["claude-sonnet-4-5"]["limit"]["output"] == 8192

def test_normalize_migrates_v1_keys():
    existing_v1 = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "custom-provider": {"name": "Custom", "package": "custom-pkg"},
            "litellm": {
                "name": "Custom LiteLLM Name",
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": "http://custom-host:8448/v1", "apiKey": "sk-123"},
                "models": {
                    "existing-model": {"name": "existing-model", "limit": {"context": 4096, "output": 1024}}
                }
            }
        },
        "plugin": ["some-plugin"],
        "enabled_providers": ["custom-provider"]
    }
    models = [
        {"model_name": "new-model", "model_info": {"max_input_tokens": 128000, "max_output_tokens": 4096}}
    ]
    res = normalize_opencode_v2_config(existing_v1, models, plugin_path="C:/plugins/opencode-agy-auth")
    assert "providers" in res
    assert "provider" not in res
    assert "custom-provider" in res["providers"]
    litellm = res["providers"]["litellm"]
    assert litellm["name"] == "Custom LiteLLM Name"
    assert litellm["package"] == "@opencode/ai/providers/openai-compatible"
    assert "npm" not in litellm
    assert "options" not in litellm
    assert litellm["settings"]["baseURL"] == "http://custom-host:8448/v1"
    assert litellm["settings"]["apiKey"] == "sk-123"
    assert "existing-model" in litellm["models"]
    assert "new-model" in litellm["models"]
    assert "plugins" in res
    assert "plugin" not in res
    assert "some-plugin" in res["plugins"]
    assert "C:/plugins/opencode-agy-auth" in res["plugins"]
    assert "google-agy" in res["enabled_providers"]

def test_normalize_preserves_custom_model_settings_and_ignores_wildcards():
    existing = {
        "providers": {
            "litellm": {
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {"baseURL": "http://10.0.0.10:8448/v1"},
                "models": {
                    "gpt-4o": {
                        "name": "Custom GPT-4o Display Name",
                        "custom_flag": True,
                        "limit": {"context": 100000, "output": 4000}
                    }
                }
            }
        }
    }
    models = [
        {"model_name": "gpt-4o", "model_info": {"max_input_tokens": 128000, "max_output_tokens": 16384}},
        {"model_name": "wildcard/*", "model_info": {}}
    ]
    res = normalize_opencode_v2_config(existing, models)
    litellm_models = res["providers"]["litellm"]["models"]
    assert "wildcard/*" not in litellm_models
    assert "gpt-4o" in litellm_models
    assert litellm_models["gpt-4o"]["custom_flag"] is True
    assert litellm_models["gpt-4o"]["limit"]["context"] == 128000
    assert litellm_models["gpt-4o"]["limit"]["output"] == 16384
