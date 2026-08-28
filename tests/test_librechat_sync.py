import pytest
import os
import yaml
from app.sync import export_librechat_config

def test_export_librechat_config_single(tmp_path):
    target_file = tmp_path / "librechat.yaml"
    initial_config = {
        "version": "1.3.13",
        "cache": True,
        "endpoints": {
            "custom": [
                {
                    "name": "LiteLLM",
                    "apiKey": "${LITELLM_API_KEY}",
                    "baseURL": "http://litellm:4000/v1",
                    "models": {
                        "default": ["old-model"],
                        "fetch": True
                    },
                    "titleConvo": True
                },
                {
                    "name": "OpenCode Agent",
                    "apiKey": "sk-dummy",
                    "baseURL": "http://10.0.0.10:8448/v1"
                }
            ]
        },
        "mcpServers": {
            "contextcortex": {
                "type": "sse",
                "url": "http://contextcortex:3000/sse"
            }
        }
    }
    with open(target_file, "w") as f:
        yaml.safe_dump(initial_config, f)

    mock_models = [
        {
            "model_name": "vertex/gemini-3.7-flash",
            "model_info": {
                "max_input_tokens": 1000000,
                "input_cost_per_token": 0.00000015,
                "output_cost_per_token": 0.00000060
            }
        },
        {
            "model_name": "deepseek-v4-flash-0731",
            "pricing": {
                "prompt_1m": 0.14,
                "completion_1m": 0.28
            },
            "max_input_tokens": 131072
        }
    ]

    res = export_librechat_config(mock_models, target_paths=[str(target_file)])
    assert res["status"] == "success"
    assert len(res["synced"]) == 1
    assert res["synced"][0]["models_count"] == 2

    with open(target_file, "r") as f:
        updated = yaml.safe_load(f)

    custom_eps = updated["endpoints"]["custom"]
    litellm_ep = next(ep for ep in custom_eps if ep["name"] == "LiteLLM")
    opencode_ep = next(ep for ep in custom_eps if ep["name"] == "OpenCode Agent")

    # Verify LiteLLM endpoint updated
    assert litellm_ep["models"]["default"] == ["vertex/gemini-3.7-flash", "deepseek-v4-flash-0731"]
    assert litellm_ep["models"]["fetch"] is True
    assert "tokenConfig" in litellm_ep
    assert litellm_ep["tokenConfig"]["vertex/gemini-3.7-flash"] == {
        "prompt": 0.15,
        "completion": 0.60,
        "context": 1000000
    }
    assert litellm_ep["tokenConfig"]["deepseek-v4-flash-0731"] == {
        "prompt": 0.14,
        "completion": 0.28,
        "context": 131072
    }

    # Verify other endpoints & configs preserved
    assert opencode_ep["name"] == "OpenCode Agent"
    assert "contextcortex" in updated["mcpServers"]

def test_export_librechat_config_multi_target(tmp_path):
    main_file = tmp_path / "main_librechat.yaml"
    public_file = tmp_path / "public_librechat.yaml"
    missing_file = tmp_path / "nonexistent.yaml"

    for f_path in [main_file, public_file]:
        with open(f_path, "w") as f:
            yaml.safe_dump({
                "version": "1.3.13",
                "endpoints": {
                    "custom": [{"name": "LiteLLM", "baseURL": "http://litellm:4000/v1"}]
                }
            }, f)

    mock_models = [
        {
            "model_name": "qwen3.7-plus",
            "pricing": {"prompt_1m": 0.40, "completion_1m": 1.20},
            "max_input_tokens": 1000000
        }
    ]

    res = export_librechat_config(mock_models, target_paths=[str(main_file), str(public_file), str(missing_file)])
    assert res["status"] == "success"
    assert len(res["synced"]) == 2
    assert len(res["skipped"]) == 1
    assert res["skipped"][0]["reason"] == "file_not_found"

    # Both existing files should be updated
    for f_path in [main_file, public_file]:
        with open(f_path, "r") as f:
            data = yaml.safe_load(f)
        ep = data["endpoints"]["custom"][0]
        assert ep["tokenConfig"]["qwen3.7-plus"]["context"] == 1000000
        assert ep["tokenConfig"]["qwen3.7-plus"]["prompt"] == 0.40
        assert ep["tokenConfig"]["qwen3.7-plus"]["completion"] == 1.20

def test_export_librechat_config_no_litellm_endpoint(tmp_path):
    file_path = tmp_path / "other_librechat.yaml"
    with open(file_path, "w") as f:
        yaml.safe_dump({
            "version": "1.3.13",
            "endpoints": {"custom": [{"name": "OtherProvider"}]}
        }, f)

    res = export_librechat_config([{"model_name": "m1"}], target_paths=[str(file_path)])
    assert len(res["synced"]) == 0
    assert len(res["skipped"]) == 1
    assert res["skipped"][0]["reason"] == "litellm_endpoint_not_found"
