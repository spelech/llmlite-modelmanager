import os
import yaml
import shutil
import asyncio
from typing import List, Dict, Any, Optional
from collections import Counter

from app.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_VERTEX_CREDS,
    app_state,
    get_app_setting,
)
from app.aliases import (
    build_model_group_aliases,
    build_model_fallbacks,
    sync_router_settings_to_litellm_db,
)
from app.opencode_sync import normalize_opencode_v2_config, export_opencode_config
from app.remote_opencode_sync import (
    get_remote_ssh_connection,
    test_remote_opencode_connection,
    sync_single_remote_host,
    export_remote_opencode_config,
)
from app.litellm_runtime import verify_litellm_healthy, restart_litellm_internal

MANAGED_PROVIDER_PREFIXES = ("openrouter/", "vertex_ai/", "local/", "ollama_chat/", "ollama/")


def is_custom_model_entry(entry: dict, model_map: Optional[Dict[str, Any]] = None) -> bool:
    """Return True if a LiteLLM model_list entry is a custom/static route (e.g., CLIAgentDispatch agy-*) not managed by discovery."""
    mid = (entry.get("model_info", {}) or {}).get("id") or (entry.get("litellm_params", {}) or {}).get("model") or ""
    if not mid:
        return False
    if model_map and mid in model_map:
        return False
    return not mid.startswith(MANAGED_PROVIDER_PREFIXES)


async def sync_models_internal(selected_ids: List[str]) -> Dict[str, Any]:
    """
    Core logic to sync selected models into LiteLLM config and OpenCode config
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
    model_group_alias = build_model_group_aliases(new_model_list, existing_aliases=existing_aliases)
    if model_group_alias:
        router_settings["model_group_alias"] = model_group_alias
        auto_fallbacks = build_model_fallbacks(model_group_alias, new_model_names)
        if auto_fallbacks:
            router_settings["fallbacks"] = auto_fallbacks
        config["router_settings"] = router_settings

    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)

    if router_settings:
        await sync_router_settings_to_litellm_db(router_settings)

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
    return {
        "status": "success",
        "updated_models": len(managed_selected_ids),
        "preserved_custom_models": len(preserved_custom_models),
        "aliases_count": len(model_group_alias) if model_group_alias else 0,
        "remote_opencode_sync": remote_opencode_res
    }
