import os
import json
import yaml
import time
import shutil
import asyncio
import httpx
from typing import List, Dict, Any, Optional
from collections import Counter

from app.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_VERTEX_CREDS,
    app_state,
    get_app_setting
)
from app.notifications import send_notification

def export_opencode_config(models: list, target_path: str = "/app/opencode_config/opencode.jsonc"):
    """Sync active LiteLLM models to OpenCode configuration file."""
    if not os.path.exists(target_path):
        return
    
    try:
        with open(target_path, "r") as f:
            content = json.load(f)
    except Exception as e:
        print(f"Error reading opencode config: {e}")
        return

    if "provider" not in content:
        content["provider"] = {}
    if "litellm" not in content["provider"]:
        content["provider"]["litellm"] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "LiteLLM Gateway",
            "options": {"baseURL": "http://10.0.0.10:8448/v1"},
            "models": {}
        }
    
    opencode_models = {}
    for m in models:
        m_name = m.get("model_name")
        if not m_name or m_name.endswith("*"):
            continue
        
        info = m.get("model_info", {})
        ctx_limit = info.get("max_input_tokens", 128000) or 128000
        out_limit = info.get("max_output_tokens", 8192) or 8192
        
        opencode_models[m_name] = {
            "name": m_name,
            "limit": {
                "context": ctx_limit,
                "output": out_limit
            }
        }
    
    content["provider"]["litellm"]["models"] = opencode_models
    
    with open(target_path, "w") as f:
        json.dump(content, f, indent=2)

async def sync_models_internal(selected_ids: List[str]) -> Dict[str, Any]:
    """
    Core logic to sync selected models into LiteLLM config and OpenCode config with
    automatic duplicate collision prevention and safety backup.
    """
    all_models = app_state.get("or_models", []) + app_state.get("vx_models", [])
    model_map = {m["id"]: m for m in all_models}
    
    config_path = get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH)
    config = {}
    if os.path.exists(config_path):
        try:
            shutil.copy2(config_path, config_path + ".bak")
        except Exception as e:
            print(f"Warning: Failed to create config backup: {e}")

        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
    
    # Analyze base model names to detect collisions across providers
    base_names = [mid.split("/")[-1] for mid in selected_ids]
    name_counts = Counter(base_names)
    
    new_model_list = []
    for mid in selected_ids:
        m_data = model_map.get(mid, {})
        pricing = m_data.get("pricing", {})
        base_name = mid.split("/")[-1]
        
        # Disambiguate model_name if duplicate base names exist across providers
        if name_counts[base_name] > 1:
            if mid.startswith("vertex_ai/"):
                model_name = f"vertex/{base_name}"
            elif mid.startswith("openrouter/"):
                model_name = f"openrouter/{base_name}"
            else:
                model_name = mid
        else:
            model_name = base_name
        
        entry = {
            "model_name": model_name,
            "litellm_params": {"model": mid},
            "model_info": {
                "id": mid,
                "input_cost_per_token": pricing.get("prompt", 0),
                "output_cost_per_token": pricing.get("completion", 0),
                "max_input_tokens": m_data.get("max_input_tokens", 0),
                "max_output_tokens": m_data.get("max_output_tokens", 0),
                "capabilities": m_data.get("capabilities", {}),
                "brand": m_data.get("brand", "other")
            }
        }
        
        if mid.startswith("openrouter/"):
            entry["litellm_params"]["api_key"] = get_app_setting("OPENROUTER_API_KEY")
        elif mid.startswith("vertex_ai/"):
            vertex_creds = get_app_setting("VERTEX_CREDENTIALS_PATH", DEFAULT_VERTEX_CREDS)
            entry["litellm_params"].update({
                "vertex_project": get_app_setting("VERTEX_PROJECT"),
                "vertex_location": get_app_setting("VERTEX_LOCATION", "global"),
                "vertex_credentials": vertex_creds
            })
            entry["model_info"]["input_cost_per_character"] = pricing.get("prompt", 0)
            entry["model_info"]["output_cost_per_character"] = pricing.get("completion", 0)
            
        new_model_list.append(entry)
    
    config["model_list"] = new_model_list
    
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
        
    export_opencode_config(config["model_list"])
    return {"status": "success", "updated_models": len(new_model_list)}

async def verify_litellm_healthy(timeout: float = 45.0) -> bool:
    """Check if LiteLLM is responding on /health."""
    urls = [
        "http://litellm:4000/health/readiness",
        "http://litellm:4000/health",
        "http://10.0.0.10:8448/health/readiness",
        "http://10.0.0.10:8448/health"
    ]
    start = time.time()
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.time() - start < timeout:
            for url in urls:
                try:
                    resp = await client.get(url)
                    if resp.status_code in [200, 204]:
                        return True
                except Exception:
                    pass
            await asyncio.sleep(1.5)
    return False

async def restart_litellm_internal() -> Dict[str, Any]:
    """
    Restarts LiteLLM container and verifies health.
    If unhealthy, automatically reverts to config.yaml.bak and restores healthy state.
    """
    config_path = get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH)
    backup_path = config_path + ".bak"
    
    try:
        import docker
        client = docker.from_env()
        container = client.containers.get("litellm")
        container.restart()
        
        healthy = await verify_litellm_healthy(timeout=45.0)
        if healthy:
            return {"status": "success", "message": "LiteLLM restarted and health verified (HTTP 200 OK)."}
        
        # If not healthy, attempt automatic rollback
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, config_path)
            container.restart()
            await verify_litellm_healthy(timeout=45.0)
            
            await send_notification(
                title="⚠️ LiteLLM Configuration Failed & Auto-Reverted",
                body="New configuration caused LiteLLM to fail health checks after restart. The previous valid configuration was automatically restored.",
                notification_type="error",
                tags="warning,rotate"
            )
            
            return {
                "status": "error",
                "reverted": True,
                "message": "LiteLLM failed health checks after restart! Automatically reverted to previous valid configuration and restored service."
            }
        else:
            return {"status": "error", "reverted": False, "message": "LiteLLM failed health checks after restart, no backup configuration found."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
