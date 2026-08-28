import asyncio
import os
import time
import yaml
import httpx
from typing import Dict, List, Optional
from google.oauth2 import service_account

from app.database import update_model_health, get_all_settings, get_setting
from app.notifications import notify_model_unavailable

DEFAULT_VERTEX_CREDS = "/app/vertex_credentials.json"
DEFAULT_CONFIG_PATH = "/app/config/config.yaml"

async def probe_model_catalog(model_id: str, settings: Dict[str, str]) -> Dict[str, any]:
    """
    Zero-Token health probe: verifies model exists in provider active catalog without generating completions.
    """
    start_time = time.time()
    try:
        if model_id.startswith("vertex_ai/"):
            short_id = model_id.split("/")[-1]
            creds_path = settings.get("VERTEX_CREDENTIALS_PATH", os.environ.get("VERTEX_CREDENTIALS_PATH", DEFAULT_VERTEX_CREDS))
            project = settings.get("VERTEX_PROJECT", os.environ.get("VERTEX_PROJECT"))
            location = settings.get("VERTEX_LOCATION", os.environ.get("VERTEX_LOCATION", "global"))
            
            if not os.path.exists(creds_path) and not settings.get("VERTEX_CREDENTIALS_JSON"):
                return {"healthy": False, "latency_ms": 0, "error": "Missing Vertex credentials"}

            scopes = ['https://www.googleapis.com/auth/cloud-platform']
            creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
            
            from google import genai
            client = genai.Client(vertexai=True, project=project, location=location, credentials=creds)
            loop = asyncio.get_running_loop()
            model_info = await loop.run_in_executor(None, lambda: client.models.get(model=short_id))
            latency = (time.time() - start_time) * 1000
            return {
                "healthy": True,
                "latency_ms": round(latency, 2),
                "response": f"Catalog Active ({getattr(model_info, 'display_name', short_id)}) [0 Tokens]",
                "error": None
            }

        elif model_id.startswith("openrouter/"):
            or_id = model_id.replace("openrouter/", "")
            url = f"https://openrouter.ai/api/v1/models/{or_id}"
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                latency = (time.time() - start_time) * 1000
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    name = data.get("name", or_id)
                    return {
                        "healthy": True,
                        "latency_ms": round(latency, 2),
                        "response": f"Catalog Active ({name}) [0 Tokens]",
                        "error": None
                    }
                else:
                    return {
                        "healthy": False,
                        "latency_ms": round(latency, 2),
                        "error": f"OpenRouter Catalog HTTP {resp.status_code}: {resp.text}",
                        "response": None
                    }
                    
        return {"healthy": False, "latency_ms": 0, "error": f"Unsupported provider: {model_id}"}
    except Exception as e:
        latency = (time.time() - start_time) * 1000
        return {"healthy": False, "latency_ms": round(latency, 2), "error": str(e), "response": None}

async def probe_model_live(model_id: str, settings: Dict[str, str]) -> Dict[str, any]:
    """
    Minimal-Token live probe: sends 1-token prompt to confirm live endpoint execution.
    """
    start_time = time.time()
    is_embed = "embed" in model_id.lower()
    
    try:
        if model_id.startswith("vertex_ai/"):
            short_id = model_id.split("/")[-1]
            creds_path = settings.get("VERTEX_CREDENTIALS_PATH", os.environ.get("VERTEX_CREDENTIALS_PATH", DEFAULT_VERTEX_CREDS))
            project = settings.get("VERTEX_PROJECT", os.environ.get("VERTEX_PROJECT"))
            location = settings.get("VERTEX_LOCATION", os.environ.get("VERTEX_LOCATION", "global"))
            
            if not os.path.exists(creds_path) and not settings.get("VERTEX_CREDENTIALS_JSON"):
                return {"healthy": False, "latency_ms": 0, "error": "Missing Vertex credentials"}

            scopes = ['https://www.googleapis.com/auth/cloud-platform']
            creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
            
            from google import genai
            client = genai.Client(vertexai=True, project=project, location=location, credentials=creds)
            loop = asyncio.get_running_loop()
            if is_embed:
                await loop.run_in_executor(None, lambda: client.models.embed_content(model=short_id, contents="1"))
                res_text = "Embedding OK"
            else:
                resp = await loop.run_in_executor(None, lambda: client.models.generate_content(model=short_id, contents="1"))
                res_text = resp.text
                
            latency = (time.time() - start_time) * 1000
            return {"healthy": True, "latency_ms": round(latency, 2), "response": res_text, "error": None}

        elif model_id.startswith("openrouter/"):
            or_id = model_id.replace("openrouter/", "")
            api_key = settings.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or ""
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            async with httpx.AsyncClient(timeout=15.0) as client:
                if is_embed:
                    url = "https://openrouter.ai/api/v1/embeddings"
                    payload = {"model": or_id, "input": "1"}
                else:
                    url = "https://openrouter.ai/api/v1/chat/completions"
                    payload = {"model": or_id, "messages": [{"role": "user", "content": "1"}], "max_tokens": 1}

                resp = await client.post(url, headers=headers, json=payload)
                latency = (time.time() - start_time) * 1000
                if resp.status_code == 200:
                    res_json = resp.json()
                    res_text = "Embedding OK" if is_embed else res_json.get("choices", [{}])[0].get("message", {}).get("content", "OK")
                    return {"healthy": True, "latency_ms": round(latency, 2), "response": res_text, "error": None}
                else:
                    err_msg = f"HTTP {resp.status_code}: {resp.text}"
                    return {"healthy": False, "latency_ms": round(latency, 2), "error": err_msg, "response": None}
                    
        return {"healthy": False, "latency_ms": 0, "error": f"Unsupported provider: {model_id}"}
    except Exception as e:
        latency = (time.time() - start_time) * 1000
        return {"healthy": False, "latency_ms": round(latency, 2), "error": str(e), "response": None}

async def probe_model(
    model_id: str,
    settings: Optional[Dict[str, str]] = None,
    mode: str = "catalog"
) -> Dict[str, any]:
    """
    Tests model responsiveness. Defaults to zero-token catalog check.
    """
    if settings is None:
        settings = await get_all_settings()
        
    if mode == "catalog":
        return await probe_model_catalog(model_id, settings)
    else:
        return await probe_model_live(model_id, settings)

async def check_active_models_health(
    config_path: str = DEFAULT_CONFIG_PATH,
    notify: bool = True,
    mode: Optional[str] = None
) -> Dict[str, any]:
    """
    Checks health of only active configured LiteLLM models.
    Defaults to zero-token catalog check unless configured otherwise.
    """
    settings = await get_all_settings()
    actual_config_path = settings.get("LITELLM_CONFIG", os.environ.get("LITELLM_CONFIG", config_path))
    probe_mode = mode or settings.get("PROBE_MODE", "catalog")
    
    if not os.path.exists(actual_config_path):
        return {"status": "error", "message": f"Config not found at {actual_config_path}", "results": []}

    try:
        with open(actual_config_path, "r") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse config: {e}", "results": []}

    model_list = cfg.get("model_list", [])
    active_mids = [
        m.get("litellm_params", {}).get("model")
        for m in model_list
        if m.get("litellm_params", {}).get("model") and "*" not in m.get("model_name", "")
    ]
    
    semaphore = asyncio.Semaphore(4)
    results = []
    
    async def _check_one(mid: str):
        async with semaphore:
            res = await probe_model(mid, settings, mode=probe_mode)
            res["model_id"] = mid
            res["mode"] = probe_mode
            await update_model_health(mid, res["healthy"], res.get("error"))
            
            if not res["healthy"] and notify:
                await notify_model_unavailable(mid, res.get("error") or "Health probe failed")
            return res

    tasks = [_check_one(mid) for mid in active_mids]
    if tasks:
        results = await asyncio.gather(*tasks)

    healthy_count = sum(1 for r in results if r["healthy"])
    unhealthy_count = sum(1 for r in results if not r["healthy"])

    return {
        "status": "success",
        "total_checked": len(results),
        "healthy": healthy_count,
        "unhealthy": unhealthy_count,
        "mode": probe_mode,
        "results": results
    }
