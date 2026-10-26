import os
import io
import re
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

MANAGED_PROVIDER_PREFIXES = ("openrouter/", "vertex_ai/", "local/", "ollama_chat/", "ollama/")

INTERNAL_ONLY_ALIASES = {
    "openclaw-default",
    "actual-brain",
    "claude-haiku-4-5",
    "anthropic/claude-haiku-4-5",
    "z-ai/glm-5.3",
    "z-ai/glm-5.3-flash",
    "google/gemini-3.8-flash",
}


def is_custom_model_entry(entry: dict, model_map: Optional[Dict[str, Any]] = None) -> bool:
    """Return True if a LiteLLM model_list entry is a custom/static route (e.g., CLIAgentDispatch agy-*) not managed by discovery."""
    mid = (entry.get("model_info", {}) or {}).get("id") or (entry.get("litellm_params", {}) or {}).get("model") or ""
    if not mid:
        return False
    if model_map and mid in model_map:
        return False
    return not mid.startswith(MANAGED_PROVIDER_PREFIXES)


def _extract_version_tuple(text: str) -> tuple:
    """Extract (major, minor, is_clean_release) tuple from a model identifier for picking the latest family model."""
    low = text.lower()
    m = re.search(r"(?:gemini-|glm-|deepseek-v|qwen|hy)(\d+)(?:\.(\d+))?", low)
    if not m:
        return (0, 0, 0)
    major = int(m.group(1))
    minor = int(m.group(2)) if m.group(2) is not None else 0
    # Prefer base release names over dated snapshots (e.g., -0731, -0813, -1017) when major.minor ties
    has_date_suffix = bool(re.search(r"-\d{4}$", low))
    return (major, minor, 0 if has_date_suffix else 1)


def build_auto_model_group_aliases(
    model_list: List[Dict[str, Any]],
    existing_aliases: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """
    Build LiteLLM router_settings.model_group_alias mapping canonical downstream aliases
    to the highest-versioned enabled model in each family.
    """
    entries = []
    name_set = set()
    for m in model_list:
        if not isinstance(m, dict):
            continue
        m_name = m.get("model_name") or ""
        mid = (m.get("model_info", {}) or {}).get("id") or (m.get("litellm_params", {}) or {}).get("model") or ""
        if m_name:
            name_set.add(m_name)
            entries.append((m_name, mid.lower()))

    def _pick_best(predicate) -> Optional[str]:
        candidates = [( _extract_version_tuple(mid), m_name ) for m_name, mid in entries if predicate(m_name, mid)]
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    aliases: Dict[str, str] = {}

    best_flash = _pick_best(
        lambda name, mid: mid.startswith("vertex_ai/gemini-")
        and mid.endswith("-flash")
        and not any(x in mid for x in ("-lite", "-image", "-tts", "-live", "-omni"))
    )
    best_flash_lite = _pick_best(
        lambda name, mid: mid.startswith("vertex_ai/gemini-") and mid.endswith("-flash-lite")
    )
    best_argon = _pick_best(
        lambda name, mid: mid.startswith("vertex_ai/gemini-") and "argon" in mid
    )
    best_glm = _pick_best(
        lambda name, mid: mid.startswith("openrouter/z-ai/glm-")
        and not any(x in mid for x in ("-flash", "-air", "-turbo", "-prime", ":"))
    )
    best_glm_flash = _pick_best(
        lambda name, mid: mid.startswith("openrouter/z-ai/glm-") and mid.endswith("-flash")
    )
    best_ds_pro = _pick_best(
        lambda name, mid: mid.startswith("openrouter/deepseek/deepseek-") and "-pro" in mid and ":" not in mid
    )
    best_ds_flash = _pick_best(
        lambda name, mid: mid.startswith("openrouter/deepseek/deepseek-")
        and "-flash" in mid
        and ":" not in mid
        and "vision" not in mid
    )
    best_qwen_flash = _pick_best(
        lambda name, mid: mid.startswith("openrouter/qwen/qwen")
        and mid.endswith("-flash")
        and not any(x in mid for x in ("-coder", "-omni"))
    )
    best_qwen_max = _pick_best(
        lambda name, mid: mid.startswith("openrouter/qwen/qwen") and mid.endswith("-max")
    )
    best_qwen_cheap = _pick_best(
        lambda name, mid: mid.startswith("openrouter/qwen/qwen")
        and any(mid.endswith(s) for s in ("-27b", "-32b", "-30b-a3b"))
    )
    best_hy4 = _pick_best(
        lambda name, mid: mid.startswith("openrouter/tencent/hy4")
    )
    best_hy3 = _pick_best(
        lambda name, mid: mid == "openrouter/tencent/hy3" or (mid.startswith("openrouter/tencent/hy3") and "preview" not in mid)
    )
    best_jev = _pick_best(
        lambda name, mid: "jev-router" in mid
    )

    if best_flash:
        aliases["opencode-default"] = best_flash
        aliases["openclaw-default"] = best_flash
        aliases["flash-latest"] = best_flash
        aliases["google/gemini-3.8-flash"] = best_flash
    if best_flash_lite:
        aliases["opencode-small"] = best_flash_lite
        aliases["flash-lite-latest"] = best_flash_lite
    if best_argon:
        aliases["argon"] = best_argon
    if best_glm:
        aliases["glm"] = best_glm
        aliases["z-ai/glm-5.3"] = best_glm
    if best_glm_flash:
        aliases["glm-flash"] = best_glm_flash
        aliases["claude-haiku-4-5"] = best_glm_flash
        aliases["anthropic/claude-haiku-4-5"] = best_glm_flash
        aliases["z-ai/glm-5.3-flash"] = best_glm_flash
    if best_ds_pro:
        aliases["deepseek-pro"] = best_ds_pro
    if best_ds_flash:
        aliases["deepseek-flash"] = best_ds_flash
        aliases["actual-brain"] = best_ds_flash
    if best_qwen_flash:
        aliases["qwen-flash"] = best_qwen_flash
    if best_qwen_max:
        aliases["qwen-max"] = best_qwen_max
    if best_qwen_cheap:
        aliases["qwen-cheap"] = best_qwen_cheap
    if best_hy4:
        aliases["hy4"] = best_hy4
    if best_hy3:
        aliases["hy3"] = best_hy3
    if best_jev:
        aliases["jev-router"] = best_jev

    # Preserve any custom user-defined aliases from existing_aliases whose target model still exists in model_list
    if existing_aliases and isinstance(existing_aliases, dict):
        for k, v in existing_aliases.items():
            if k not in aliases and v in name_set:
                aliases[k] = v

    return aliases


def build_auto_fallbacks(
    aliases: Dict[str, str],
    enabled_names: set
) -> List[Dict[str, List[str]]]:
    """Build valid LiteLLM router_settings.fallbacks using currently enabled models."""
    fallbacks: List[Dict[str, List[str]]] = []

    def _valid(candidates: List[Optional[str]]) -> List[str]:
        out = []
        for c in candidates:
            if c and c in enabled_names and c not in out:
                out.append(c)
        return out

    if "agy" in enabled_names:
        fb = _valid([aliases.get("argon"), aliases.get("deepseek-flash"), aliases.get("qwen-flash")])
        if fb:
            fallbacks.append({"agy": fb})

    flash_target = aliases.get("flash-latest")
    if flash_target and flash_target in enabled_names:
        fb = _valid([aliases.get("qwen-flash"), aliases.get("deepseek-flash"), aliases.get("glm-flash")])
        if fb:
            fallbacks.append({flash_target: fb})

    flash_lite_target = aliases.get("flash-lite-latest")
    if flash_lite_target and flash_lite_target in enabled_names:
        fb = _valid([aliases.get("deepseek-flash"), aliases.get("glm-flash"), aliases.get("qwen-flash")])
        if fb:
            fallbacks.append({flash_lite_target: fb})

    if "gemini-3.1-flash-image" in enabled_names and "gemini-nano-banana-2.1" in enabled_names:
        fallbacks.append({"gemini-3.1-flash-image": ["gemini-nano-banana-2.1"]})

    return fallbacks


def normalize_opencode_v2_config(
    content: dict,
    models: list,
    plugin_path: Optional[str] = None,
    removed_model_names: Optional[set] = None,
    model_group_alias: Optional[Dict[str, str]] = None
) -> dict:
    """Normalizes OpenCode configuration to native V2 schema, upgrading legacy V1 fields and syncing models."""
    if "$schema" not in content:
        content["$schema"] = "https://opencode.ai/config.json"

    # Migrate legacy "provider" map to "providers"
    if "provider" in content and isinstance(content["provider"], dict):
        legacy_provider = content.pop("provider")
        if "providers" not in content or not isinstance(content["providers"], dict):
            content["providers"] = {}
        for p_id, p_val in legacy_provider.items():
            if p_id not in content["providers"]:
                content["providers"][p_id] = p_val
    elif "providers" not in content or not isinstance(content["providers"], dict):
        content["providers"] = {}

    providers = content["providers"]
    if "litellm" not in providers or not isinstance(providers["litellm"], dict):
        providers["litellm"] = {
            "name": "LiteLLM Gateway",
            "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": "http://10.0.0.10:8448/v1"},
            "models": {}
        }
    else:
        litellm = providers["litellm"]
        litellm["package"] = "@opencode/ai/providers/openai-compatible"
        litellm.pop("npm", None)

        settings = litellm.get("settings")
        if not isinstance(settings, dict):
            settings = {}

        if "options" in litellm and isinstance(litellm["options"], dict):
            legacy_opts = litellm.pop("options")
            for k, v in legacy_opts.items():
                if k not in settings:
                    settings[k] = v

        if "baseURL" not in settings:
            settings["baseURL"] = "http://10.0.0.10:8448/v1"
        litellm["settings"] = settings
        if "models" not in litellm or not isinstance(litellm["models"], dict):
            litellm["models"] = {}

    # Build lookup of active LiteLLM models and their token limits
    model_limits_by_name = {}
    opencode_models = {}
    for m in models:
        m_name = m.get("model_name")
        if not m_name or m_name.endswith("*"):
            continue
        info = m.get("model_info", {})
        ctx_limit = info.get("max_input_tokens", 128000) or 128000
        out_limit = info.get("max_output_tokens", 8192) or 8192
        limit_dict = {
            "context": ctx_limit,
            "output": out_limit
        }
        model_limits_by_name[m_name] = limit_dict
        opencode_models[m_name] = {
            "name": m_name,
            "limit": limit_dict
        }

    existing_oc_models = dict(providers["litellm"].get("models", {}))

    if model_group_alias and isinstance(model_group_alias, dict):
        # Alias-focused sync: only export clean, non-internal aliases into OpenCode
        alias_models = {}
        for reserved in ("opencode-default", "opencode-small"):
            if reserved in existing_oc_models and isinstance(existing_oc_models[reserved], dict):
                alias_models[reserved] = dict(existing_oc_models[reserved])
        for alias_name, target_name in model_group_alias.items():
            if alias_name in INTERNAL_ONLY_ALIASES or "/" in alias_name:
                continue
            target_limit = model_limits_by_name.get(target_name, {"context": 128000, "output": 8192})
            entry_cfg = {
                "name": alias_name,
                "limit": dict(target_limit)
            }
            if alias_name in existing_oc_models and isinstance(existing_oc_models[alias_name], dict):
                merged_entry = dict(existing_oc_models[alias_name])
                merged_entry.update(entry_cfg)
                alias_models[alias_name] = merged_entry
            else:
                alias_models[alias_name] = entry_cfg
        providers["litellm"]["models"] = alias_models
    else:
        merged_models = existing_oc_models
        if removed_model_names:
            for rem_name in removed_model_names:
                if rem_name not in opencode_models:
                    merged_models.pop(rem_name, None)

        for m_name, m_cfg in opencode_models.items():
            if m_name in merged_models and isinstance(merged_models[m_name], dict):
                merged_models[m_name].update(m_cfg)
            else:
                merged_models[m_name] = m_cfg
        providers["litellm"]["models"] = merged_models

    # Migrate legacy "plugin" to "plugins"
    plugins = content.get("plugins")
    if not isinstance(plugins, list):
        legacy_plugin = content.pop("plugin", None)
        if isinstance(legacy_plugin, list):
            plugins = legacy_plugin
        elif isinstance(legacy_plugin, str):
            plugins = [legacy_plugin]
        else:
            plugins = []
        content["plugins"] = plugins
    else:
        legacy_plugin = content.pop("plugin", None)
        if isinstance(legacy_plugin, list):
            for p in legacy_plugin:
                if p not in plugins:
                    plugins.append(p)
        elif isinstance(legacy_plugin, str) and legacy_plugin not in plugins:
            plugins.append(legacy_plugin)

    # Optional remote plugin registration
    if plugin_path:
        norm_plugin = plugin_path.replace("\\", "/")
        if norm_plugin not in plugins:
            plugins.append(norm_plugin)

        enabled_providers = content.get("enabled_providers")
        if isinstance(enabled_providers, list) and "google-agy" not in enabled_providers:
            enabled_providers.append("google-agy")

    return content

def export_opencode_config(
    models: list,
    target_path: str = "/app/opencode_config/opencode.jsonc",
    removed_model_names: Optional[set] = None,
    model_group_alias: Optional[Dict[str, str]] = None
):
    """Sync active LiteLLM models to OpenCode configuration file using native V2 schema."""
    if not os.path.exists(target_path):
        return
    
    try:
        with open(target_path, "r") as f:
            content = json.load(f)
    except Exception as e:
        print(f"Error reading opencode config: {e}")
        return

    content = normalize_opencode_v2_config(
        content,
        models,
        removed_model_names=removed_model_names,
        model_group_alias=model_group_alias
    )
    
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

    raw_host = (host or get_app_setting("OPENCODE_REMOTE_HOST", "") or "").strip()
    target_host = raw_host.split(",")[0].strip() if raw_host else ""
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
    """Test SSH connectivity and verify target file/directory accessibility on remote host(s)."""
    raw_host = (host if host is not None else (get_app_setting("OPENCODE_REMOTE_HOST", "") or "")).strip()
    hosts = [h.strip() for h in raw_host.split(",") if h.strip()]
    if not hosts:
        return {
            "status": "error",
            "message": "Remote OpenCode Host and User must be configured."
        }

    target_port = port or get_app_setting("OPENCODE_REMOTE_PORT", 22)
    target_user = (user or get_app_setting("OPENCODE_REMOTE_USER", "")).strip()
    check_config_path = (config_path if config_path is not None else (get_app_setting("OPENCODE_REMOTE_CONFIG_PATH", "") or "")).strip()

    if len(hosts) == 1:
        single_host = hosts[0]
        client = None
        sftp = None
        try:
            client, sftp = get_remote_ssh_connection(
                host=single_host, port=port, user=user, key_str=key_str, passphrase=passphrase
            )
            path_status = "not_checked"
            if check_config_path:
                try:
                    sftp.stat(check_config_path)
                    path_status = "exists"
                except FileNotFoundError:
                    path_status = "not_found_will_create"
                except Exception as pe:
                    path_status = f"error: {pe}"
            return {
                "status": "success",
                "message": f"Successfully authenticated to {target_user}@{single_host}:{target_port}",
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

    # Multi-host testing
    successes = []
    failures = []
    host_results = {}
    overall_path_status = "not_checked"

    for h in hosts:
        client = None
        sftp = None
        try:
            client, sftp = get_remote_ssh_connection(
                host=h, port=port, user=user, key_str=key_str, passphrase=passphrase, timeout=5
            )
            path_status = "not_checked"
            if check_config_path:
                try:
                    sftp.stat(check_config_path)
                    path_status = "exists"
                except FileNotFoundError:
                    path_status = "not_found_will_create"
                except Exception as pe:
                    path_status = f"error: {pe}"
            successes.append(h)
            host_results[h] = {"status": "success", "config_path_status": path_status}
            overall_path_status = path_status
        except Exception as e:
            failures.append(f"{h} ({e})")
            host_results[h] = {"status": "error", "error": str(e)}
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

    if not failures:
        return {
            "status": "success",
            "message": f"Successfully authenticated to all {len(hosts)} hosts ({', '.join(hosts)})",
            "config_path_status": overall_path_status,
            "hosts": hosts,
            "details": host_results
        }
    elif successes:
        return {
            "status": "error",
            "message": f"Connected to {len(successes)}/{len(hosts)} hosts. Failed: {'; '.join(failures)}",
            "config_path_status": overall_path_status,
            "details": host_results
        }
    else:
        return {
            "status": "error",
            "message": f"Failed to connect to all hosts: {'; '.join(failures)}",
            "details": host_results
        }

def sync_single_remote_host(
    target_host: str,
    models: list,
    config_path: str,
    plugin_path: str,
    port: Optional[int] = None,
    user: Optional[str] = None,
    key_str: Optional[str] = None,
    passphrase: Optional[str] = None,
    timeout: int = 10,
    removed_model_names: Optional[set] = None,
    model_group_alias: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Safely synchronize OpenCode configuration to a single remote host."""
    client = None
    sftp = None
    try:
        client, sftp = get_remote_ssh_connection(
            host=target_host,
            port=port,
            user=user,
            key_str=key_str,
            passphrase=passphrase,
            timeout=timeout
        )

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
            raise RuntimeError(f"Error reading remote opencode config: {e}")

        content = normalize_opencode_v2_config(
            content,
            models,
            plugin_path=plugin_path,
            removed_model_names=removed_model_names,
            model_group_alias=model_group_alias
        )
        synced_count = len(content.get("providers", {}).get("litellm", {}).get("models", {}))

        tmp_path = config_path + ".tmp"
        bak_path = config_path + ".bak"

        # Create remote backup if file already exists
        if file_exists and raw_data:
            try:
                with sftp.open(bak_path, "w") as bak_f:
                    bak_f.write(raw_data)
            except Exception as be:
                print(f"Warning [{target_host}]: Failed to create remote backup file {bak_path}: {be}")

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
            "host": target_host,
            "status": "success",
            "remote_path": config_path,
            "models_count": synced_count
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

def export_remote_opencode_config(
    models: list,
    removed_model_names: Optional[set] = None,
    model_group_alias: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Sync active LiteLLM models and optional plugin configuration to remote host(s) over SSH."""
    enabled_str = str(get_app_setting("OPENCODE_REMOTE_ENABLED", "false")).lower()
    if enabled_str not in ("true", "1", "yes"):
        return {"status": "skipped", "reason": "remote_sync_disabled"}

    config_path = (get_app_setting("OPENCODE_REMOTE_CONFIG_PATH", "") or "").strip()
    if not config_path:
        return {"status": "skipped", "reason": "missing_remote_config_path"}

    hosts_raw = (get_app_setting("OPENCODE_REMOTE_HOST", "") or "").strip()
    hosts = [h.strip() for h in hosts_raw.split(",") if h.strip()]
    if not hosts:
        hosts = [""]

    plugin_path = (get_app_setting("OPENCODE_REMOTE_PLUGIN_PATH", "") or "").strip()
    valid_models_count = len([m for m in models if m.get("model_name") and not m.get("model_name", "").endswith("*")])

    results = []
    successes = []
    failures = []

    for target_host in hosts:
        try:
            res = sync_single_remote_host(
                target_host=target_host,
                models=models,
                config_path=config_path,
                plugin_path=plugin_path,
                removed_model_names=removed_model_names,
                model_group_alias=model_group_alias
            )
            results.append(res)
            if res.get("status") == "success":
                successes.append(target_host)
            else:
                failures.append(f"{target_host}: {res.get('error', 'unknown error')}")
        except Exception as e:
            err_msg = f"{target_host}: {e}"
            failures.append(err_msg)
            results.append({"host": target_host, "status": "failed", "error": str(e)})

    if failures:
        warning_msg = f"Remote OpenCode sync warning: {'; '.join(failures)}"
        print(warning_msg)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(send_notification("sync_warning", warning_msg), loop)
            else:
                loop.run_until_complete(send_notification("sync_warning", warning_msg))
        except Exception:
            pass

    if successes and not failures:
        status = "success"
    elif successes and failures:
        status = "partial"
    else:
        status = "failed"

    return {
        "status": status,
        "remote_path": config_path,
        "hosts": hosts,
        "success_hosts": successes,
        "failed_hosts": failures,
        "results": results,
        "models_count": valid_models_count
    }


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

            # Clamp negative rates for tokenConfig
            p_prompt = max(0.0, p_prompt)
            p_completion = max(0.0, p_completion)

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
    with automatic duplicate collision prevention, preservation of custom/static routes (e.g. agy-*),
    and safety backup.
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

    existing_model_list = config.get("model_list", []) or []
    old_model_names = {m.get("model_name") for m in existing_model_list if isinstance(m, dict) and m.get("model_name")}

    preserved_custom_models = [
        m for m in existing_model_list
        if isinstance(m, dict) and is_custom_model_entry(m, model_map)
    ]
    custom_identifiers = set()
    for m in preserved_custom_models:
        if m.get("model_name"):
            custom_identifiers.add(m["model_name"])
        m_id = (m.get("model_info", {}) or {}).get("id")
        if m_id:
            custom_identifiers.add(m_id)
        lp_model = (m.get("litellm_params", {}) or {}).get("model")
        if lp_model:
            custom_identifiers.add(lp_model)

    managed_selected_ids = [mid for mid in selected_ids if mid not in custom_identifiers]
    
    # Analyze base model names to detect collisions across providers
    base_names = [mid.removeprefix("local/") if mid.startswith("local/") else mid.split("/")[-1] for mid in managed_selected_ids]
    name_counts = Counter(base_names)
    
    new_model_list = list(preserved_custom_models)
    for mid in managed_selected_ids:
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
                    "pricing_tier": "cheap"
                }
            }
        else:
            tier_val = m_data.get("tier", "moderate")
            in_cost = float(pricing.get("prompt", 0) or 0)
            out_cost = float(pricing.get("completion", 0) or 0)
            if in_cost < 0 or pricing.get("is_dynamic_router"):
                in_cost = 0.0
            if out_cost < 0 or pricing.get("is_dynamic_router"):
                out_cost = 0.0

            entry = {
                "model_name": model_name,
                "litellm_params": {"model": mid},
                "model_info": {
                    "id": mid,
                    "input_cost_per_token": in_cost,
                    "output_cost_per_token": out_cost,
                    "max_input_tokens": m_data.get("max_input_tokens", 0),
                    "max_output_tokens": m_data.get("max_output_tokens", 0),
                    "capabilities": m_data.get("capabilities", {}),
                    "benchmarks": m_data.get("benchmarks", {}),
                    "brand": m_data.get("brand", "other"),
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
    new_model_names = {m.get("model_name") for m in new_model_list if isinstance(m, dict) and m.get("model_name")}
    removed_model_names = old_model_names - new_model_names

    router_settings = config.get("router_settings")
    if not isinstance(router_settings, dict):
        router_settings = {}
    existing_aliases = router_settings.get("model_group_alias") if isinstance(router_settings.get("model_group_alias"), dict) else None
    model_group_alias = build_auto_model_group_aliases(new_model_list, existing_aliases=existing_aliases)
    if model_group_alias:
        router_settings["model_group_alias"] = model_group_alias
        auto_fallbacks = build_auto_fallbacks(model_group_alias, new_model_names)
        if auto_fallbacks:
            router_settings["fallbacks"] = auto_fallbacks
        config["router_settings"] = router_settings
    
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
        
    export_opencode_config(
        config["model_list"],
        removed_model_names=removed_model_names,
        model_group_alias=model_group_alias
    )
    remote_opencode_res = await asyncio.to_thread(
        export_remote_opencode_config,
        config["model_list"],
        removed_model_names,
        model_group_alias
    )
    librechat_res = export_librechat_config(config["model_list"])
    return {
        "status": "success",
        "updated_models": len(managed_selected_ids),
        "preserved_custom_models": len(preserved_custom_models),
        "aliases_count": len(model_group_alias),
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
