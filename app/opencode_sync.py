import os
import json
from typing import Dict, Optional


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
        # Data-driven alias sync: export aliases defined in LiteLLM router_settings.model_group_alias
        alias_models = {}
        for reserved in ("opencode-default", "opencode-small"):
            if reserved in existing_oc_models and isinstance(existing_oc_models[reserved], dict):
                alias_models[reserved] = dict(existing_oc_models[reserved])
        for alias_name, target_name in model_group_alias.items():
            if "/" in alias_name:
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
