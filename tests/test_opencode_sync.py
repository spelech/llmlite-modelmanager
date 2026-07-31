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
