import pytest
import io
import json
from unittest.mock import MagicMock, patch

from app.sync import (
    get_remote_ssh_connection,
    test_remote_opencode_connection as run_test_remote_opencode_connection,
    export_remote_opencode_config
)

def test_export_remote_opencode_disabled():
    with patch("app.sync.get_app_setting", return_value="false"):
        res = export_remote_opencode_config([])
        assert res["status"] == "skipped"
        assert res["reason"] == "remote_sync_disabled"

def test_export_remote_opencode_missing_config_path():
    def mock_get_setting(key, default=None):
        if key == "OPENCODE_REMOTE_ENABLED":
            return "true"
        if key == "OPENCODE_REMOTE_CONFIG_PATH":
            return ""
        return default

    with patch("app.sync.get_app_setting", side_effect=mock_get_setting):
        res = export_remote_opencode_config([])
        assert res["status"] == "skipped"
        assert res["reason"] == "missing_remote_config_path"

def test_get_remote_ssh_connection_missing_host_or_user():
    with patch("app.sync.get_app_setting", return_value=""):
        with pytest.raises(ValueError, match="Remote OpenCode Host and User must be configured"):
            get_remote_ssh_connection()

def test_get_remote_ssh_connection_invalid_key():
    with pytest.raises(ValueError, match="Failed to parse provided SSH Private Key"):
        get_remote_ssh_connection(
            host="192.168.1.100",
            port=22,
            user="testuser",
            key_str="INVALID_KEY_DATA"
        )

def test_test_remote_opencode_connection_failure():
    with patch("app.sync.get_remote_ssh_connection", side_effect=Exception("Connection refused")):
        res = run_test_remote_opencode_connection(host="192.168.1.100", user="testuser")
        assert res["status"] == "error"
        assert "Connection refused" in res["message"]

def test_test_remote_opencode_connection_success():
    mock_client = MagicMock()
    mock_sftp = MagicMock()
    mock_sftp.stat.return_value = MagicMock()

    with patch("app.sync.get_remote_ssh_connection", return_value=(mock_client, mock_sftp)):
        res = run_test_remote_opencode_connection(
            host="192.168.1.100",
            port=22,
            user="testuser",
            config_path="C:/Users/test/.config/opencode/opencode.json"
        )
        assert res["status"] == "success"
        assert res["config_path_status"] == "exists"
        mock_sftp.close.assert_called_once()
        mock_client.close.assert_called_once()

def test_export_remote_opencode_config_merge_and_atomic_write():
    existing_remote_json = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "mcp-router": {"type": "remote", "url": "http://10.0.0.10:8026/sse"}
        },
        "enabled_providers": ["litellm"],
        "provider": {
            "litellm": {
                "name": "LiteLLM Gateway",
                "options": {
                    "baseURL": "http://10.0.0.10:8448/v1",
                    "apiKey": "sk-secret-existing"
                },
                "models": {
                    "old-model": {"name": "old-model", "limit": {"context": 32000, "output": 4096}}
                }
            }
        }
    }

    mock_client = MagicMock()
    mock_sftp = MagicMock()

    # In-memory remote storage simulation
    remote_files = {
        "C:/Users/test/.config/opencode/opencode.json": json.dumps(existing_remote_json).encode("utf-8")
    }

    class MockFile:
        def __init__(self, path, mode):
            self.path = path
            self.mode = mode
            self.buf = io.BytesIO(remote_files.get(path, b"")) if "r" in mode else io.BytesIO()

        def read(self):
            return self.buf.getvalue()

        def write(self, data):
            if isinstance(data, str):
                data = data.encode("utf-8")
            remote_files[self.path] = data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_open(path, mode="r"):
        if "r" in mode and path not in remote_files:
            raise FileNotFoundError(f"No such file: {path}")
        return MockFile(path, mode)

    def mock_rename(src, dst):
        if src in remote_files:
            remote_files[dst] = remote_files.pop(src)

    def mock_remove(path):
        remote_files.pop(path, None)

    mock_sftp.open.side_effect = mock_open
    mock_sftp.rename.side_effect = mock_rename
    mock_sftp.remove.side_effect = mock_remove

    settings_map = {
        "OPENCODE_REMOTE_ENABLED": "true",
        "OPENCODE_REMOTE_CONFIG_PATH": "C:/Users/test/.config/opencode/opencode.json",
        "OPENCODE_REMOTE_PLUGIN_PATH": "C:\\Users\\test\\repos\\opencode-agy-auth"
    }

    with patch("app.sync.get_app_setting", side_effect=lambda k, d=None: settings_map.get(k, d)), \
         patch("app.sync.get_remote_ssh_connection", return_value=(mock_client, mock_sftp)):

        models_to_sync = [
            {
                "model_name": "gemini-2.5-pro",
                "model_info": {"max_input_tokens": 2000000, "max_output_tokens": 65536}
            }
        ]

        res = export_remote_opencode_config(models_to_sync)
        assert res["status"] == "success"
        assert res["models_count"] == 1

        # Check backup was created
        assert "C:/Users/test/.config/opencode/opencode.json.bak" in remote_files
        bak_data = json.loads(remote_files["C:/Users/test/.config/opencode/opencode.json.bak"].decode("utf-8"))
        assert "old-model" in bak_data["provider"]["litellm"]["models"]

        # Check target config content
        updated_data = json.loads(remote_files["C:/Users/test/.config/opencode/opencode.json"].decode("utf-8"))
        
        # 1. Preserved existing fields
        assert updated_data["provider"]["litellm"]["options"]["apiKey"] == "sk-secret-existing"
        assert "mcp-router" in updated_data["mcp"]
        assert "old-model" in updated_data["provider"]["litellm"]["models"]

        # 2. Updated new model
        assert "gemini-2.5-pro" in updated_data["provider"]["litellm"]["models"]
        assert updated_data["provider"]["litellm"]["models"]["gemini-2.5-pro"]["limit"]["context"] == 2000000

        # 3. Plugin registration & forward slash normalization
        assert "plugin" in updated_data
        assert "C:/Users/test/repos/opencode-agy-auth" in updated_data["plugin"]

        # 4. google-agy in enabled_providers
        assert "google-agy" in updated_data["enabled_providers"]
