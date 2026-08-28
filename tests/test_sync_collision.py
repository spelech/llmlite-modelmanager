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
