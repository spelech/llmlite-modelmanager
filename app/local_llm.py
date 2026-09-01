import os
import json
import time
import httpx
from typing import List, Dict, Any, Optional

from app.config import (
    app_state,
    get_app_setting
)
from app.capabilities import extract_capabilities, resolve_benchmarks_for_model
from app.discovery import process_and_track_discovered_models

DEFAULT_LOCAL_LLM_URL = "http://10.0.0.21:5246"
LOCAL_CACHE_FILE = "/app/config/local_models_cache.json"
LOCAL_CACHE_EXPIRY_DAYS = 7


def map_local_capabilities(raw_caps: Optional[List[str]] = None, model_name: str = "") -> Dict[str, bool]:
    """
    Map L³M² capability strings into standardized boolean feature flags.
    'vision' -> image_in=True
    'tools' -> function_calling=True
    """
    if raw_caps is not None and len(raw_caps) > 0:
        caps_lower = [str(c).lower() for c in raw_caps]
        return {
            "text_in": True,
            "text_out": True,
            "image_in": any(k in caps_lower for k in ["vision", "image", "vl", "multimodal"]),
            "image_out": any(k in caps_lower for k in ["image-gen", "image_out", "draw", "diffusion"]),
            "audio_in": any(k in caps_lower for k in ["audio", "speech", "voice"]),
            "audio_out": any(k in caps_lower for k in ["tts", "audio-out", "voice-out"]),
            "video_in": any(k in caps_lower for k in ["video", "video-in"]),
            "video_out": any(k in caps_lower for k in ["video-gen", "video-out"]),
            "pdf_in": any(k in caps_lower for k in ["pdf", "document"]),
            "function_calling": any(k in caps_lower for k in ["tools", "tool", "function", "function_calling"]),
            "streaming": True
        }
    
    # Fallback to general heuristics if raw capabilities are not provided
    extracted = extract_capabilities("", model_name)
    extracted["text_in"] = True
    extracted["text_out"] = True
    extracted["streaming"] = True
    return extracted


async def fetch_local_models(base_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch model list from L³M² /api/models endpoint, normalize metadata, and return standardized list.
    """
    url = (base_url or get_app_setting("LOCAL_LLM_URL", DEFAULT_LOCAL_LLM_URL)).rstrip("/")
    api_url = f"{url}/api/models"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                print(f"L³M² returned non-200 status code: {resp.status_code}")
                return []
            
            data = resp.json()
            raw_models = data.get("models", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            
            models = []
            for m in raw_models:
                model_name = m.get("model") or m.get("name") or ""
                if not model_name:
                    continue
                
                model_id = model_name if model_name.startswith("local/") else f"local/{model_name}"
                display_name = m.get("name") or model_name
                details = m.get("details") or {}
                engine = m.get("engine") or "ollama"
                raw_caps = m.get("capabilities", [])
                
                # Context length fallback to 131072 if unspecified
                ctx_len = details.get("context_length")
                max_input_tokens = int(ctx_len) if ctx_len is not None else 131072
                max_output_tokens = int(details.get("max_output_tokens", 8192))
                
                pricing = {
                    "prompt": 0.0,
                    "completion": 0.0,
                    "prompt_1m": 0.0,
                    "completion_1m": 0.0
                }

                model_item = {
                    "id": model_id,
                    "name": display_name,
                    "brand": "ollama",
                    "engine": engine,
                    "tier": "cheap",
                    "pricing": pricing,
                    "max_input_tokens": max_input_tokens,
                    "max_output_tokens": max_output_tokens,
                    "capabilities": map_local_capabilities(raw_caps, model_name),
                    "benchmarks": resolve_benchmarks_for_model(model_name, app_state.get("or_models", [])),
                    "details": details,
                    "size": m.get("size", 0),
                    "digest": m.get("digest", ""),
                    "modified_at": m.get("modified_at", "")
                }
                models.append(model_item)
            
            return sorted(models, key=lambda x: x["name"])
    except Exception as e:
        print(f"Error fetching local models from {api_url}: {e}")
        return []


async def verify_and_cache_local_models(base_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Discover local models from L³M², cache results locally with timestamp, update app_state, and track in SQLite.
    Falls back to cache if offline.
    """
    models = await fetch_local_models(base_url)

    if models:
        app_state["local_models"] = models
        app_state["last_local_verification_time"] = time.time()

        try:
            cache_dir = os.path.dirname(LOCAL_CACHE_FILE)
            if cache_dir and not os.path.exists(cache_dir):
                try:
                    os.makedirs(cache_dir, exist_ok=True)
                except Exception:
                    pass
            with open(LOCAL_CACHE_FILE, "w") as f:
                json.dump({"timestamp": app_state["last_local_verification_time"], "models": models}, f, indent=2)
        except Exception as e:
            print(f"Error saving local models cache: {e}")

        try:
            await process_and_track_discovered_models(models, notify=False)
        except Exception as e:
            print(f"Error tracking local models in DB: {e}")

        return models

    # Fallback to disk cache if L³M² is offline
    if os.path.exists(LOCAL_CACHE_FILE):
        try:
            with open(LOCAL_CACHE_FILE, "r") as f:
                cache_data = json.load(f)
                cached_ts = cache_data.get("timestamp", 0)
                if time.time() - cached_ts < (LOCAL_CACHE_EXPIRY_DAYS * 24 * 3600):
                    cached_models = cache_data.get("models", [])
                    app_state["local_models"] = cached_models
                    app_state["last_local_verification_time"] = cached_ts
                    return cached_models
        except Exception as e:
            print(f"Error loading local models cache: {e}")

    return []
