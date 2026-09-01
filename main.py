import os
import json
import yaml
import time
import asyncio
from typing import List, Dict, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from app.database import (
    init_db,
    get_all_settings,
    set_setting,
    get_setting,
    get_all_discovered_models,
    get_unhealthy_models
)
from app.notifications import send_notification
from app.discovery import classify_model_tier, process_and_track_discovered_models
from app.health import probe_model, check_active_models_health
from app.capabilities import extract_capabilities, resolve_benchmarks_for_model, GEMINI_SPECS, FALLBACK_PRICING
from app.config import (
    app_state,
    get_app_setting,
    refresh_app_settings,
    APP_VERSION,
    APP_BUILD_TIME,
    DEFAULT_CONFIG_PATH,
    DEFAULT_VERTEX_CREDS,
    PROXY_URL,
    CACHE_FILE,
    CACHE_EXPIRY_DAYS,
    DEFAULT_LOCATION
)
from app.vertex import (
    get_google_access_token,
    fetch_vertex_model_metadata,
    fetch_vertex_billing_skus,
    fetch_vertex_publisher_models,
    verify_and_cache_vertex_models,
    update_vertex_creds_file
)
from app.openrouter import get_openrouter_models
from app.local_llm import verify_and_cache_local_models
from app.sync import (
    export_opencode_config,
    export_librechat_config,
    sync_models_internal,
    verify_litellm_healthy,
    restart_litellm_internal
)
from app.mcp_server import mcp, set_app_state_ref

set_app_state_ref(app_state)
templates = Jinja2Templates(directory="app/templates")

async def initial_load_models():
    """Load OpenRouter models, local models, and check cache for Vertex on startup."""
    app_state["or_models"] = await get_openrouter_models()
    await verify_and_cache_local_models()
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                cache_data = json.load(f)
                if time.time() - cache_data.get("timestamp", 0) < (CACHE_EXPIRY_DAYS * 24 * 3600):
                    models = cache_data.get("models", [])
                    for m in models:
                        if "capabilities" not in m:
                            m["capabilities"] = extract_capabilities("", m["id"])
                        if "tier" not in m:
                            m["tier"] = classify_model_tier(m)
                        if "benchmarks" not in m or not m["benchmarks"]:
                            m["benchmarks"] = resolve_benchmarks_for_model(m["id"], app_state.get("or_models", []))
                    app_state["vx_models"] = models
                    app_state["last_verification_time"] = cache_data.get("timestamp", 0)
                    await process_and_track_discovered_models(app_state["or_models"] + models + app_state["local_models"], notify=False)
                    return
    except Exception as e:
        print(f"Cache load error: {e}")
        
    asyncio.create_task(verify_and_cache_vertex_models())

async def periodic_health_monitor():
    """Periodic background loop checking active model health and alerting outages."""
    while True:
        try:
            interval_hours = float(await get_setting("HEALTH_CHECK_INTERVAL_HOURS", "24"))
            await asyncio.sleep(max(300, interval_hours * 3600))
            print("Running periodic model health check (0 tokens / catalog mode)...")
            config_path = get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH)
            probe_mode = await get_setting("PROBE_MODE", "catalog")
            await check_active_models_health(config_path=config_path, notify=True, mode=probe_mode)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error in periodic health monitor: {e}")
            await asyncio.sleep(600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await refresh_app_settings()
    update_vertex_creds_file()
    await initial_load_models()
    
    # Start periodic health monitor
    monitor_task = asyncio.create_task(periodic_health_monitor())
    try:
        yield
    finally:
        monitor_task.cancel()

app = FastAPI(title="LiteLLM Manager", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount FastMCP endpoints for Streamable HTTP and SSE protocols
app.mount("/mcp", mcp.http_app(transport="http"))
app.mount("/sse", mcp.http_app(transport="sse"))

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={
            "or_models": app_state["or_models"], 
            "vx_models": app_state["vx_models"],
            "local_models": app_state.get("local_models", []),
            "version": APP_VERSION,
            "build_time": APP_BUILD_TIME
        }
    )

@app.post("/test")
async def test_model_endpoint(model_id: str = Form(...)):
    """Test model availability directly via provider APIs (1-token live probe)."""
    res = await probe_model(model_id, app_state["settings"], mode="live")
    if res["healthy"]:
        return {"status": "success", "response": res.get("response", "OK"), "latency_ms": res.get("latency_ms")}
    return {"status": "error", "message": res.get("error", "Unknown error")}

@app.post("/force-refresh")
async def force_refresh():
    if os.path.exists(CACHE_FILE):
        try:
            os.remove(CACHE_FILE)
        except Exception:
            pass
    app_state["or_models"] = await get_openrouter_models()
    await verify_and_cache_local_models()
    await verify_and_cache_vertex_models()
    return {"status": "success"}

@app.post("/restart-litellm")
async def restart_litellm_endpoint():
    return await restart_litellm_internal()

@app.get("/api/settings")
async def api_get_settings():
    return await get_all_settings()

@app.post("/api/settings")
async def api_update_settings(data: Dict[str, str]):
    for k, v in data.items():
        await set_setting(k, v)
    await refresh_app_settings()
    update_vertex_creds_file()
    return {"status": "success"}

@app.get("/api/config")
async def get_config():
    try:
        with open(get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH), "r") as f:
            config = yaml.safe_load(f) or {}
            model_list = config.get("model_list", [])
            selected_ids = [
                m.get("model_info", {}).get("id") or m.get("litellm_params", {}).get("model")
                for m in model_list
                if (m.get("model_info", {}).get("id") or m.get("litellm_params", {}).get("model"))
            ]
            return {"selected_ids": selected_ids}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/sync/opencode")
async def sync_opencode():
    config_path = get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH)
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f) or {}
            models = config.get("model_list", [])
            export_opencode_config(models)
            return {"status": "success", "exported_models": len(models)}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Config file not found"}

@app.post("/api/sync/librechat")
async def sync_librechat():
    config_path = get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH)
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f) or {}
            models = config.get("model_list", [])
            res = export_librechat_config(models)
            return {"status": "success", "exported_models": len(models), "results": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Config file not found"}

@app.post("/sync")
async def sync_models_endpoint(request: Request):
    form_data = await request.form()
    selected_ids = form_data.getlist("models")
    return await sync_models_internal(selected_ids)

@app.get("/api/models")
async def api_models():
    return {
        "openrouter": app_state["or_models"],
        "vertex": app_state["vx_models"],
        "local": app_state.get("local_models", [])
    }

@app.get("/api/models/discovered")
async def api_discovered_models():
    models = await get_all_discovered_models()
    return [{"id": m.id, "name": m.name, "tier": m.tier, "provider": m.provider, "is_healthy": m.is_healthy, "last_error": m.last_error} for m in models]

@app.post("/api/health/check")
async def api_health_check(payload: Optional[Dict[str, str]] = None):
    mode = payload.get("mode") if payload else None
    config_path = get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH)
    return await check_active_models_health(config_path=config_path, notify=True, mode=mode)

@app.post("/api/notifications/test")
async def api_test_notification(payload: Optional[Dict[str, str]] = None):
    url = payload.get("url") if payload else None
    return await send_notification(
        title="LiteLLM Manager Test Notification",
        body="Apprise / Ntfy connectivity test is successful from LiteLLM Manager.",
        notification_type="info",
        tags="test,robot",
        override_url=url
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
