import os
import re
import json
from typing import List, Dict, Any, Optional

from app.config import get_app_setting


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


def build_model_group_aliases(
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
        candidates = [(_extract_version_tuple(mid), m_name) for m_name, mid in entries if predicate(m_name, mid)]
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
        lambda name, mid: mid.startswith("vertex_ai/gemini-")
        and mid.endswith("-flash-lite")
        and "-image" not in mid
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
        aliases["flash-latest"] = best_flash
    if best_flash_lite:
        aliases["opencode-small"] = best_flash_lite
        aliases["flash-lite-latest"] = best_flash_lite
    if best_argon:
        aliases["argon"] = best_argon
    if best_glm:
        aliases["glm"] = best_glm
    if best_glm_flash:
        aliases["glm-flash"] = best_glm_flash
    if best_ds_pro:
        aliases["deepseek-pro"] = best_ds_pro
    if best_ds_flash:
        aliases["deepseek-flash"] = best_ds_flash
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

    # Preserve any custom user-defined clean aliases whose target model is still enabled
    if existing_aliases and isinstance(existing_aliases, dict):
        for k, v in existing_aliases.items():
            if k not in aliases and "/" not in k and v in name_set:
                aliases[k] = v

    return aliases


def build_model_fallbacks(
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


async def sync_router_settings_to_litellm_db(
    router_settings: Dict[str, Any],
    database_url: Optional[str] = None
) -> bool:
    """Update LiteLLM_Config router_settings in PostgreSQL if present so DB state matches config.yaml."""
    db_url = database_url or get_app_setting("LITELLM_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        db_url = "postgresql://litellm:litellm_pass_99@litellm-db:5432/litellm"
    clean_db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    try:
        import asyncpg
        conn = await asyncpg.connect(clean_db_url, timeout=2.0)
        try:
            await conn.execute(
                """
                UPDATE "LiteLLM_Config"
                SET param_value = $1::jsonb
                WHERE param_name = 'router_settings';
                """,
                json.dumps(router_settings)
            )
            return True
        finally:
            await conn.close()
    except Exception:
        return False
