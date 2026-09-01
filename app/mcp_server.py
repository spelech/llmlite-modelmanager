import os
import yaml
import json
from typing import List, Dict, Optional
from fastmcp import FastMCP

from app.database import (
    get_all_settings,
    set_setting,
    get_all_discovered_models,
    get_unhealthy_models
)
from app.notifications import send_notification
from app.health import probe_model, check_active_models_health
from app.discovery import classify_model_tier

mcp = FastMCP(
    "LiteLLMManager",
    instructions="Manage LiteLLM Gateway models, test live provider endpoints, check availability health, and configure routing."
)

# Reference to shared state in main.py
_app_state_ref = None

def set_app_state_ref(state: Dict):
    global _app_state_ref
    _app_state_ref = state

def get_current_models_list() -> List[Dict]:
    if _app_state_ref:
        return (
            _app_state_ref.get("or_models", [])
            + _app_state_ref.get("vx_models", [])
            + _app_state_ref.get("local_models", [])
        )
    return []

@mcp.tool
async def list_active_models() -> List[Dict]:
    """
    List all models currently enabled and configured in the LiteLLM Gateway.
    """
    settings = await get_all_settings()
    config_path = settings.get("LITELLM_CONFIG", os.environ.get("LITELLM_CONFIG", "/app/config/config.yaml"))
    
    if not os.path.exists(config_path):
        return []
        
    try:
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("model_list", [])
    except Exception as e:
        return [{"error": str(e)}]

@mcp.tool
async def list_available_models(
    provider: Optional[str] = None,
    tier: Optional[str] = None,
    search: Optional[str] = None,
    brand: Optional[str] = None,
    min_coding_score: Optional[float] = None,
    min_intelligence_score: Optional[float] = None,
    min_agentic_score: Optional[float] = None
) -> List[Dict]:
    """
    Query available models from OpenRouter, Vertex AI, and Local LLM (L³M²/Ollama) with filters.
    
    :param provider: Filter by provider ('openrouter', 'vertex_ai', 'local', or 'ollama').
    :param tier: Filter by pricing tier ('cheap', 'moderate', or 'frontier').
    :param search: Keyword search in model ID or name.
    :param brand: Filter by model creator/brand (e.g. 'google', 'anthropic', 'openai', 'deepseek', 'meta-llama', 'ollama').
    :param min_coding_score: Minimum coding benchmark score (0-100).
    :param min_intelligence_score: Minimum intelligence benchmark score (0-100).
    :param min_agentic_score: Minimum agentic benchmark score (0-100).
    """
    all_models = get_current_models_list()
    
    results = []
    for m in all_models:
        mid = m.get("id", "")
        m_brand = m.get("brand", "").lower()
        m_tier = m.get("tier") or classify_model_tier(m)
        m_provider = mid.split("/")[0] if "/" in mid else "unknown"
        benchmarks = m.get("benchmarks", {})
        
        if provider:
            p_low = provider.lower()
            if p_low in ["local", "ollama"]:
                if not (mid.startswith("local/") or m_provider.lower() in ["local", "ollama"]):
                    continue
            elif m_provider.lower() != p_low:
                continue
        if tier and m_tier.lower() != tier.lower():
            continue
        if brand and brand.lower() not in m_brand:
            continue
        if search:
            s_low = search.lower()
            if s_low not in mid.lower() and s_low not in m.get("name", "").lower():
                continue
                
        if min_coding_score is not None:
            c_score = benchmarks.get("coding")
            if c_score is None or float(c_score) < min_coding_score:
                continue
        if min_intelligence_score is not None:
            i_score = benchmarks.get("intelligence")
            if i_score is None or float(i_score) < min_intelligence_score:
                continue
        if min_agentic_score is not None:
            a_score = benchmarks.get("agentic")
            if a_score is None or float(a_score) < min_agentic_score:
                continue
                
        m_copy = dict(m)
        m_copy["tier"] = m_tier
        results.append(m_copy)
        
    return results

@mcp.tool
async def get_trending_models(tier: Optional[str] = None) -> Dict[str, List[Dict]]:
    """
    Get top trending models categorized by pricing tiers (cheap, moderate, frontier).
    """
    all_models = get_current_models_list()
    by_tier = {"frontier": [], "moderate": [], "cheap": []}
    
    for m in all_models:
        t = m.get("tier") or classify_model_tier(m)
        if t in by_tier:
            by_tier[t].append(m)
        else:
            by_tier["moderate"].append(m)
            
    # Sort each tier by popularity
    for k in by_tier:
        by_tier[k].sort(key=lambda x: x.get("popularity", 999))
        
    if tier and tier in by_tier:
        return {tier: by_tier[tier][:20]}
        
    return {
        "frontier": by_tier["frontier"][:10],
        "moderate": by_tier["moderate"][:10],
        "cheap": by_tier["cheap"][:10]
    }

@mcp.tool
async def test_model(model_id: str, mode: str = "live") -> Dict[str, any]:
    """
    Perform a live generation or embedding probe directly against a model to test latency and availability.
    
    :param model_id: Full model identifier (e.g. 'openrouter/anthropic/claude-3.5-sonnet' or 'vertex_ai/gemini-2.5-pro').
    :param mode: Probe mode ('catalog' for 0-token catalog check, or 'live' for 1-token live ping).
    """
    return await probe_model(model_id, mode=mode)

@mcp.tool
async def check_model_health(send_alerts: bool = True, mode: str = "catalog") -> Dict[str, any]:
    """
    Probe all currently active LiteLLM models and report health status.
    Defaults to zero-token catalog check.
    
    :param send_alerts: Whether to trigger Apprise/Ntfy alerts for failing models.
    :param mode: 'catalog' (0-token metadata check) or 'live' (1-token ping).
    """
    settings = await get_all_settings()
    config_path = settings.get("LITELLM_CONFIG", os.environ.get("LITELLM_CONFIG", "/app/config/config.yaml"))
    return await check_active_models_health(config_path=config_path, notify=send_alerts, mode=mode)

@mcp.tool
async def sync_models(model_ids: List[str]) -> Dict[str, any]:
    """
    Set the active models in LiteLLM configuration and export to OpenCode and LibreChat configurations.
    
    :param model_ids: List of model IDs to enable (e.g. ['openrouter/deepseek/deepseek-chat', 'vertex_ai/gemini-2.5-flash']).
    """
    from main import sync_models_internal
    return await sync_models_internal(model_ids)

@mcp.tool
async def sync_librechat() -> Dict[str, any]:
    """
    Export and sync the active LiteLLM models and true token limits into all configured LibreChat yaml files.
    """
    from app.sync import export_librechat_config
    settings = await get_all_settings()
    config_path = settings.get("LITELLM_CONFIG", os.environ.get("LITELLM_CONFIG", "/app/config/config.yaml"))
    if not os.path.exists(config_path):
        return {"status": "error", "message": "LiteLLM configuration file not found."}
    
    try:
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f) or {}
        models = cfg.get("model_list", [])
        return export_librechat_config(models)
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool
async def add_model(model_id: str) -> Dict[str, any]:
    """
    Add a single model to the active LiteLLM configuration without removing existing ones.
    """
    active = await list_active_models()
    active_ids = [
        m.get("litellm_params", {}).get("model")
        for m in active
        if m.get("litellm_params", {}).get("model") and "*" not in m.get("model_name", "")
    ]
    if model_id not in active_ids:
        active_ids.append(model_id)
        return await sync_models(active_ids)
    return {"status": "already_present", "model_id": model_id, "active_count": len(active_ids)}

@mcp.tool
async def remove_model(model_id: str) -> Dict[str, any]:
    """
    Remove a model from the active LiteLLM configuration.
    """
    active = await list_active_models()
    active_ids = [
        m.get("litellm_params", {}).get("model")
        for m in active
        if m.get("litellm_params", {}).get("model") and "*" not in m.get("model_name", "")
    ]
    if model_id in active_ids:
        active_ids.remove(model_id)
        return await sync_models(active_ids)
    return {"status": "not_found", "model_id": model_id, "active_count": len(active_ids)}

@mcp.tool
async def restart_litellm() -> Dict[str, any]:
    """
    Restart the LiteLLM container with health check verification and automatic rollback on failure.
    """
    from main import restart_litellm_internal
    return await restart_litellm_internal()

@mcp.tool
async def get_settings() -> Dict[str, str]:
    """
    Retrieve all manager settings (API keys, Apprise URL, notification flags).
    """
    return await get_all_settings()

@mcp.tool
async def update_settings(settings: Dict[str, str]) -> Dict[str, any]:
    """
    Update configuration settings in SQLite.
    
    :param settings: Key-value map of settings (e.g. {'APPRISE_URL': 'http://apprise:8000/notify/system', 'NOTIFICATION_ENABLED': 'true'}).
    """
    for k, v in settings.items():
        await set_setting(k, str(v))
    return {"status": "success", "updated_keys": list(settings.keys())}

@mcp.tool
async def send_test_notification(custom_url: Optional[str] = None) -> Dict[str, any]:
    """
    Send a test notification via Apprise or Ntfy to verify push alert connectivity.
    """
    return await send_notification(
        title="LiteLLM Manager Test Notification",
        body="This is a test notification from the LiteLLM Manager MCP Server.",
        notification_type="info",
        tags="test,robot",
        override_url=custom_url
    )
