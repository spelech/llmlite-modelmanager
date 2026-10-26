import os
import io
import json
import asyncio
from typing import Dict, Any, Optional

from app.config import get_app_setting
from app.notifications import send_notification
from app.opencode_sync import normalize_opencode_v2_config


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
