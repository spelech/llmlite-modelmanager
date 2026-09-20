import os
import io
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
    get_app_setting,
    get_librechat_config_paths
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
    
    existing_models = content.get("provider", {}).get("litellm", {}).get("models", {})
    merged_models = dict(existing_models) if isinstance(existing_models, dict) else {}
    for m_name, m_cfg in opencode_models.items():
        if m_name in merged_models and isinstance(merged_models[m_name], dict):
            merged_models[m_name].update(m_cfg)
        else:
            merged_models[m_name] = m_cfg

    content["provider"]["litellm"]["models"] = merged_models
    
    with open(target_path, "w") as f:
        json.dump(content, f, indent=2)

def get_remote_ssh_connection(
    host: Optional[str] = None,
    port: Optional[int] = None,
    user: Optional[str] = None,
    key_str: Optional[str] = None,
    passphrase: Optional[str] = None,
    key_path: Optional[str] = None,
    timeout: int = 10
):
    """Establishes an SSH connection and returns (client, sftp) handles using in-memory or file-based keys."""
    import paramiko

    target_host = (host or get_app_setting("OPENCODE_REMOTE_HOST", "") or "").strip()
    target_port = int(port or get_app_setting("OPENCODE_REMOTE_PORT", 22) or 22)
    target_user = (user or get_app_setting("OPENCODE_REMOTE_USER", "") or "").strip()
    target_key = key_str if key_str is not None else (get_app_setting("OPENCODE_REMOTE_KEY", "") or "")
    target_passphrase = passphrase if passphrase is not None else get_app_setting("OPENCODE_REMOTE_KEY_PASSPHRASE", None)

    if not target_host or not target_user:
        raise ValueError("Remote OpenCode Host and User must be configured.")

    pkey = None
    if target_key and target_key.strip():
        buf = io.StringIO(target_key.strip())
        for key_cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
            buf.seek(0)
            try:
                pkey = key_cls.from_private_key(buf, password=target_passphrase)
                break
            except Exception:
                continue
        if pkey is None:
            raise ValueError("Failed to parse provided SSH Private Key (supported formats: Ed25519, RSA, ECDSA).")
    elif key_path and os.path.exists(key_path):
        for key_cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
            try:
                pkey = key_cls.from_private_key_file(key_path, password=target_passphrase)
                break
            except Exception:
                continue

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=target_host,
        port=target_port,
        username=target_user,
        pkey=pkey,
        timeout=timeout,
        look_for_keys=False if pkey else True,
        allow_agent=False if pkey else True
    )
    sftp = client.open_sftp()
    return client, sftp

def test_remote_opencode_connection(
    host: Optional[str] = None,
    port: Optional[int] = None,
    user: Optional[str] = None,
    key_str: Optional[str] = None,
    passphrase: Optional[str] = None,
    config_path: Optional[str] = None
) -> Dict[str, Any]:
    """Test SSH connectivity and verify target file/directory accessibility on remote host."""
    client = None
    sftp = None
    try:
        client, sftp = get_remote_ssh_connection(
            host=host, port=port, user=user, key_str=key_str, passphrase=passphrase
        )
        target_path = (config_path or get_app_setting("OPENCODE_REMOTE_CONFIG_PATH", "") or "").strip()
        path_status = "not_checked"
        if target_path:
            try:
                sftp.stat(target_path)
                path_status = "exists"
            except FileNotFoundError:
                path_status = "not_found_will_create"
            except Exception as pe:
                path_status = f"error: {pe}"
        
        target_user = (user or get_app_setting("OPENCODE_REMOTE_USER", "")).strip()
        target_host = (host or get_app_setting("OPENCODE_REMOTE_HOST", "")).strip()
        target_port = port or get_app_setting("OPENCODE_REMOTE_PORT", 22)
        return {
            "status": "success",
            "message": f"Successfully authenticated to {target_user}@{target_host}:{target_port}",
            "config_path_status": path_status
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
    finally:
        if sftp:
            try:
                sftp.close()
            except Exception:
                pass
        if client:
            try:
                client.close()
            except Exception:
                pass

def export_remote_opencode_config(models: list) -> Dict[str, Any]:
    """Sync active LiteLLM models and optional plugin configuration to remote host over SSH."""
    enabled_str = str(get_app_setting("OPENCODE_REMOTE_ENABLED", "false")).lower()
    if enabled_str not in ("true", "1", "yes"):
        return {"status": "skipped", "reason": "remote_sync_disabled"}

    config_path = (get_app_setting("OPENCODE_REMOTE_CONFIG_PATH", "") or "").strip()
    if not config_path:
        return {"status": "skipped", "reason": "missing_remote_config_path"}

    plugin_path = (get_app_setting("OPENCODE_REMOTE_PLUGIN_PATH", "") or "").strip()

    client = None
    sftp = None
    try:
        client, sftp = get_remote_ssh_connection()
    except Exception as e:
        err_msg = f"Remote OpenCode SSH connection failed: {e}"
        print(err_msg)
        send_notification("sync_warning", err_msg)
        return {"status": "failed", "error": err_msg}

    try:
        content = {}
        raw_data = ""
        file_exists = False
        try:
            with sftp.open(config_path, "r") as f:
                raw_bytes = f.read()
                raw_data = raw_bytes.decode("utf-8")
                content = json.loads(raw_data)
                file_exists = True
        except FileNotFoundError:
            content = {"$schema": "https://opencode.ai/config.json"}
        except Exception as e:
            err_msg = f"Error reading remote opencode config: {e}"
            print(err_msg)
            send_notification("sync_warning", err_msg)
            return {"status": "failed", "error": err_msg}

        if "provider" not in content or not isinstance(content["provider"], dict):
            content["provider"] = {}
        if "litellm" not in content["provider"] or not isinstance(content["provider"]["litellm"], dict):
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

        existing_models = content.get("provider", {}).get("litellm", {}).get("models", {})
        merged_models = dict(existing_models) if isinstance(existing_models, dict) else {}
        for m_name, m_cfg in opencode_models.items():
            if m_name in merged_models and isinstance(merged_models[m_name], dict):
                merged_models[m_name].update(m_cfg)
            else:
                merged_models[m_name] = m_cfg
        content["provider"]["litellm"]["models"] = merged_models

        # Optional plugin path registration and provider enabling
        if plugin_path:
            norm_plugin = plugin_path.replace("\\", "/")
            plugins = content.get("plugin", [])
            if not isinstance(plugins, list):
                plugins = [plugins] if plugins else []
            if norm_plugin not in plugins:
                plugins.append(norm_plugin)
            content["plugin"] = plugins

            enabled_providers = content.get("enabled_providers")
            if isinstance(enabled_providers, list) and "google-agy" not in enabled_providers:
                enabled_providers.append("google-agy")

        tmp_path = config_path + ".tmp"
        bak_path = config_path + ".bak"

        # Create remote backup if file already exists
        if file_exists and raw_data:
            try:
                with sftp.open(bak_path, "w") as bak_f:
                    bak_f.write(raw_data)
            except Exception as be:
                print(f"Warning: Failed to create remote backup file {bak_path}: {be}")

        # Write to tmp file
        with sftp.open(tmp_path, "w") as tmp_f:
            tmp_f.write(json.dumps(content, indent=2))

        # Atomic replacement for Windows/Linux SFTP servers
        if file_exists:
            try:
                sftp.remove(config_path)
            except Exception:
                pass
        sftp.rename(tmp_path, config_path)

        return {
            "status": "success",
            "remote_path": config_path,
            "models_count": len(opencode_models)
        }
    except Exception as e:
        err_msg = f"Failed to sync remote opencode config: {e}"
        print(err_msg)
        send_notification("sync_warning", err_msg)
        return {"status": "failed", "error": err_msg}
    finally:
        if sftp:
            try:
                sftp.close()
            except Exception:
                pass
        if client:
            try:
                client.close()
            except Exception:
                pass

def export_librechat_config(models: list, target_paths: Optional[List[str]] = None) -> Dict[str, Any]:
    """Sync active LiteLLM models and token limits into librechat.yaml configurations."""
    if target_paths is None:
        target_paths = get_librechat_config_paths()
    elif isinstance(target_paths, str):
        target_paths = [target_paths]

    synced_targets = []
    skipped_targets = []

    for path in target_paths:
        if not os.path.exists(path):
            skipped_targets.append({"path": path, "reason": "file_not_found"})
            continue

        try:
            with open(path, "r") as f:
                config = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Error reading librechat config at {path}: {e}")
            skipped_targets.append({"path": path, "reason": f"read_error: {e}"})
            continue

        endpoints = config.setdefault("endpoints", {})
        custom_list = endpoints.setdefault("custom", [])

        litellm_ep = next((ep for ep in custom_list if ep.get("name") == "LiteLLM"), None)
        if not litellm_ep:
            skipped_targets.append({"path": path, "reason": "litellm_endpoint_not_found"})
            continue

        token_config = litellm_ep.setdefault("tokenConfig", {})
        model_list = []

        for m in models:
            m_name = m.get("model_name")
            if not m_name or m_name.endswith("*"):
                continue

            info = m.get("model_info", {})
            ctx_limit = info.get("max_input_tokens") or m.get("max_input_tokens") or 128000

            pricing = m.get("pricing", {})
            if "prompt_1m" in pricing:
                p_prompt = float(pricing.get("prompt_1m", 0.0))
                p_completion = float(pricing.get("completion_1m", 0.0))
            else:
                p_prompt_raw = info.get("input_cost_per_token") or info.get("input_cost_per_character") or pricing.get("prompt", 0.0)
                p_completion_raw = info.get("output_cost_per_token") or info.get("output_cost_per_character") or pricing.get("completion", 0.0)
                try:
                    p_prompt = float(p_prompt_raw) * 1_000_000
                    p_completion = float(p_completion_raw) * 1_000_000
                except (ValueError, TypeError):
                    p_prompt = 0.0
                    p_completion = 0.0

            model_list.append(m_name)
            token_config[m_name] = {
                "prompt": round(p_prompt, 4),
                "completion": round(p_completion, 4),
                "context": int(ctx_limit)
            }

        if "models" not in litellm_ep or not isinstance(litellm_ep["models"], dict):
            litellm_ep["models"] = {"fetch": True}

        litellm_ep["models"]["default"] = model_list
        litellm_ep["tokenConfig"] = token_config

        try:
            with open(path, "w") as f:
                yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)
            synced_targets.append({"path": path, "models_count": len(model_list)})
        except Exception as e:
            print(f"Error writing librechat config to {path}: {e}")
            skipped_targets.append({"path": path, "reason": f"write_error: {e}"})

    return {
        "status": "success" if synced_targets else "partial_or_skipped",
        "synced": synced_targets,
        "skipped": skipped_targets
    }

async def sync_models_internal(selected_ids: List[str]) -> Dict[str, Any]:
    """
    Core logic to sync selected models into LiteLLM config, OpenCode config, and LibreChat config
    with automatic duplicate collision prevention and safety backup.
    """
    all_models = app_state.get("or_models", []) + app_state.get("vx_models", []) + app_state.get("local_models", [])
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
    base_names = [mid.removeprefix("local/") if mid.startswith("local/") else mid.split("/")[-1] for mid in selected_ids]
    name_counts = Counter(base_names)
    
    new_model_list = []
    for mid in selected_ids:
        m_data = model_map.get(mid, {})
        pricing = m_data.get("pricing", {})
        if mid.startswith("local/"):
            base_name = mid.removeprefix("local/")
        else:
            base_name = mid.split("/")[-1]
        
        # Disambiguate model_name if duplicate base names exist across providers
        if name_counts[base_name] > 1:
            if mid.startswith("vertex_ai/"):
                model_name = f"vertex/{base_name}"
            elif mid.startswith("openrouter/"):
                model_name = f"openrouter/{base_name}"
            elif mid.startswith("local/"):
                model_name = f"local/{base_name}"
            else:
                model_name = mid
        else:
            model_name = base_name
        
        if mid.startswith("local/"):
            local_url = get_app_setting("LOCAL_LLM_URL", "http://10.0.0.21:5246")
            engine = m_data.get("engine", "ollama")
            if engine in ("vllm", "openai"):
                litellm_params = {
                    "model": f"openai/{base_name}",
                    "api_base": f"{local_url.rstrip('/')}/v1"
                }
            else:
                litellm_params = {
                    "model": f"ollama_chat/{base_name}",
                    "api_base": local_url
                }

            entry = {
                "model_name": model_name,
                "litellm_params": litellm_params,
                "model_info": {
                    "id": mid,
                    "input_cost_per_token": 0.0,
                    "output_cost_per_token": 0.0,
                    "max_input_tokens": m_data.get("max_input_tokens", 0),
                    "max_output_tokens": m_data.get("max_output_tokens", 0),
                    "capabilities": m_data.get("capabilities", {}),
                    "benchmarks": m_data.get("benchmarks", {}),
                    "brand": m_data.get("brand", "ollama"),
                    "tier": "cheap",
                    "pricing_tier": "cheap"
                }
            }
        else:
            tier_val = m_data.get("tier", "moderate")
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
                    "benchmarks": m_data.get("benchmarks", {}),
                    "brand": m_data.get("brand", "other"),
                    "tier": tier_val,
                    "pricing_tier": tier_val
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
    remote_opencode_res = await asyncio.to_thread(export_remote_opencode_config, config["model_list"])
    librechat_res = export_librechat_config(config["model_list"])
    return {
        "status": "success",
        "updated_models": len(new_model_list),
        "remote_opencode_sync": remote_opencode_res,
        "librechat_sync": librechat_res
    }

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
