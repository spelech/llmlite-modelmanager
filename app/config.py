import os
from typing import Dict, Any, Optional, List
from app.database import get_all_settings

# --- Default Paths & Keys (Internal Fallbacks) ---
DEFAULT_CONFIG_PATH = "/app/config/config.yaml"
DEFAULT_VERTEX_CREDS = "/app/vertex_credentials.json"
DEFAULT_LIBRECHAT_CONFIG_PATHS = [
    "/app/librechat_config/main_librechat.yaml",
    "/app/librechat_config/public_kb_librechat.yaml",
    "/app/librechat_config/librechat.yaml",
    "/containers/ai/librechat/librechat.yaml",
    "/containers/public_kb/librechat/librechat.yaml"
]
PROXY_URL = "http://litellm:4000/v1/chat/completions"

CACHE_FILE = "/app/config/verified_models_cache.json"
CACHE_EXPIRY_DAYS = 7
DEFAULT_LOCATION = "global"

# App Versioning
if os.path.exists("VERSION"):
    with open("VERSION", "r") as f:
        APP_VERSION = f.read().strip()
else:
    APP_VERSION = "dev"
APP_BUILD_TIME = os.environ.get("APP_BUILD_TIME", "unknown")

# Global App State
app_state: Dict[str, Any] = {
    "or_models": [],
    "vx_models": [],
    "local_models": [],
    "last_verification_time": 0,
    "settings": {}  # Loaded from DB on startup
}

def get_app_setting(key: str, default=None):
    """Helper to get setting from app_state or environment."""
    return app_state["settings"].get(key) or os.environ.get(key) or default

def get_librechat_config_paths() -> List[str]:
    """Retrieve list of LibreChat configuration file paths to sync."""
    paths_str = get_app_setting("LIBRECHAT_CONFIG_PATHS")
    if paths_str:
        return [p.strip() for p in paths_str.split(",") if p.strip()]
    return DEFAULT_LIBRECHAT_CONFIG_PATHS

async def refresh_app_settings():
    """Load settings from DB into memory."""
    app_state["settings"] = await get_all_settings()
