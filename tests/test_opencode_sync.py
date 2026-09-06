import pytest
import os
import json
from main import export_opencode_config

def test_export_opencode_config(tmp_path):
    target_file = tmp_path / "opencode.jsonc"
    target_file.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "mcp": {"mcp-router": {"type": "remote", "url": "http://10.0.0.10:8026/sse"}},
        "provider": {"litellm": {"options": {"baseURL": "http://10.0.0.10:8448/v1"}, "models": {}}}
    }))
    
    mock_models = [
        {
            "model_name": "gemini-2.5-flash",
            "model_info": {"max_input_tokens": 1000000, "max_output_tokens": 8192}
        }
    ]
    
    export_opencode_config(mock_models, target_path=str(target_file))
    
    data = json.loads(target_file.read_text())
    assert "gemini-2.5-flash" in data["provider"]["litellm"]["models"]
    assert data["provider"]["litellm"]["models"]["gemini-2.5-flash"]["limit"]["context"] == 1000000


def test_export_opencode_config_preserves_custom_models_and_settings(tmp_path):
    target_file = tmp_path / "opencode.jsonc"
    initial_config = {
        "$schema": "https://opencode.ai/config.json",
        "model": "litellm/vertex/gemini-3.8-flash",
        "small_model": "litellm/gemini-3.5-flash-lite",
        "enabled_providers": ["litellm", "google-agy"],
        "disabled_providers": ["google-vertex", "openrouter"],
        "mcp": {"mcg": {"type": "remote", "url": "http://10.0.0.10:8026/sse"}},
        "provider": {
            "litellm": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "LiteLLM Gateway",
                "options": {
                    "baseURL": "http://10.0.0.10:8448/v1",
                    "apiKey": "sk-testkey"
                },
                "models": {
                    "custom-fast-alias": {
                        "name": "custom-fast-alias",
                        "limit": {"context": 128000, "output": 4096},
                        "custom_field": "preserved"
                    },
                    "gemini-2.5-flash": {
                        "name": "gemini-2.5-flash",
                        "limit": {"context": 500000, "output": 4096},
                        "custom_variant": "low"
                    }
                }
            }
        }
    }
    target_file.write_text(json.dumps(initial_config))

    mock_synced_models = [
        {
            "model_name": "gemini-2.5-flash",
            "model_info": {"max_input_tokens": 1000000, "max_output_tokens": 65536}
        },
        {
            "model_name": "deepseek-v4-flash",
            "model_info": {"max_input_tokens": 1310720, "max_output_tokens": 131072}
        }
    ]

    export_opencode_config(mock_synced_models, target_path=str(target_file))

    result = json.loads(target_file.read_text())
    # 1. Top-level keys preserved
    assert result["model"] == "litellm/vertex/gemini-3.8-flash"
    assert result["small_model"] == "litellm/gemini-3.5-flash-lite"
    assert result["enabled_providers"] == ["litellm", "google-agy"]
    assert result["disabled_providers"] == ["google-vertex", "openrouter"]
    assert result["provider"]["litellm"]["options"]["apiKey"] == "sk-testkey"

    # 2. Custom unmanaged model alias preserved
    models = result["provider"]["litellm"]["models"]
    assert "custom-fast-alias" in models
    assert models["custom-fast-alias"]["custom_field"] == "preserved"

    # 3. Existing model updated while preserving extra custom keys
    assert "gemini-2.5-flash" in models
    assert models["gemini-2.5-flash"]["limit"]["context"] == 1000000
    assert models["gemini-2.5-flash"]["limit"]["output"] == 65536
    assert models["gemini-2.5-flash"]["custom_variant"] == "low"

    # 4. New model added
    assert "deepseek-v4-flash" in models
    assert models["deepseek-v4-flash"]["limit"]["context"] == 1310720

