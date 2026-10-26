import os
import time
import shutil
import asyncio
import httpx
from typing import Dict, Any

from app.config import DEFAULT_CONFIG_PATH, get_app_setting
from app.notifications import send_notification


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
