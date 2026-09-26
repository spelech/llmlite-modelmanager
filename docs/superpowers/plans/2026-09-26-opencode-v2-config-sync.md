# OpenCode v2 Configuration Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update `litellm-manager` to write native OpenCode v2 configuration files (`providers`, `package`, `settings`, `plugins`) and seamlessly upgrade existing v1 configuration files in-place during local and remote syncs.

**Architecture:** Implement a single pure normalization function `normalize_opencode_v2_config(content: dict, models: list, plugin_path: Optional[str] = None) -> dict` in `app/sync.py`. Use this normalizer in both `export_opencode_config` (local) and `export_remote_opencode_config` (remote SFTP) to guarantee identical migration behavior and format consistency.

**Tech Stack:** Python 3.12, FastAPI, Paramiko (SFTP), Pytest.

## Global Constraints
- Native runtime package: `"@opencode/ai/providers/openai-compatible"`.
- Native baseURL location: `"settings"` -> `{"baseURL": "http://10.0.0.10:8448/v1"}`.
- Map names: `"providers"` (not `"provider"`), `"plugins"` (not `"plugin"`).
- Existing custom models, non-litellm providers, and unrelated top-level settings must be preserved without loss.
- Version bump: Already bumped to `0.15.0` in `VERSION`.

---

### Task 1: Core Normalizer Implementation (`normalize_opencode_v2_config`)

**Files:**
- Modify: `ai/litellm-manager/app/sync.py`
- Create/Modify: `ai/litellm-manager/tests/test_opencode_v2_normalizer.py`

**Interfaces:**
- Produces: `normalize_opencode_v2_config(content: dict, models: list, plugin_path: Optional[str] = None) -> dict`
- Consumes: LiteLLM model lists with `model_name` and `model_info: {max_input_tokens, max_output_tokens}`

- [ ] **Step 1: Write the failing unit tests for `normalize_opencode_v2_config`**

Create `tests/test_opencode_v2_normalizer.py` with tests for:
1. Fresh configuration initialization (`providers.litellm` with `@opencode/ai/providers/openai-compatible`, `settings.baseURL`, and models).
2. Legacy v1 migration (`provider` -> `providers`, `npm` -> `package`, `options` -> `settings`).
3. Model token limits merging and preserving custom model fields.
4. Legacy `plugin` -> `plugins` array migration and remote plugin injection.

```python
import pytest
from app.sync import normalize_opencode_v2_config

def test_normalize_fresh_config():
    models = [
        {"model_name": "claude-sonnet-4-5", "model_info": {"max_input_tokens": 200000, "max_output_tokens": 8192}}
    ]
    res = normalize_opencode_v2_config({}, models)
    assert res["$schema"] == "https://opencode.ai/config.json"
    assert "providers" in res
    assert "provider" not in res
    litellm = res["providers"]["litellm"]
    assert litellm["package"] == "@opencode/ai/providers/openai-compatible"
    assert litellm["settings"]["baseURL"] == "http://10.0.0.10:8448/v1"
    assert "options" not in litellm
    assert "npm" not in litellm
    assert "claude-sonnet-4-5" in litellm["models"]
    assert litellm["models"]["claude-sonnet-4-5"]["limit"]["context"] == 200000

def test_normalize_migrates_v1_keys():
    existing_v1 = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "custom-provider": {"name": "Custom", "package": "custom-pkg"},
            "litellm": {
                "name": "Custom LiteLLM Name",
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": "http://custom-host:8448/v1", "apiKey": "sk-123"},
                "models": {
                    "existing-model": {"name": "existing-model", "limit": {"context": 4096, "output": 1024}}
                }
            }
        },
        "plugin": ["some-plugin"],
        "enabled_providers": ["custom-provider"]
    }
    models = [
        {"model_name": "new-model", "model_info": {"max_input_tokens": 128000, "max_output_tokens": 4096}}
    ]
    res = normalize_opencode_v2_config(existing_v1, models, plugin_path="C:/plugins/opencode-agy-auth")
    assert "providers" in res
    assert "provider" not in res
    assert "custom-provider" in res["providers"]
    litellm = res["providers"]["litellm"]
    assert litellm["name"] == "Custom LiteLLM Name"
    assert litellm["package"] == "@opencode/ai/providers/openai-compatible"
    assert "npm" not in litellm
    assert "options" not in litellm
    assert litellm["settings"]["baseURL"] == "http://custom-host:8448/v1"
    assert litellm["settings"]["apiKey"] == "sk-123"
    assert "existing-model" in litellm["models"]
    assert "new-model" in litellm["models"]
    assert "plugins" in res
    assert "plugin" not in res
    assert "some-plugin" in res["plugins"]
    assert "C:/plugins/opencode-agy-auth" in res["plugins"]
    assert "google-agy" in res["enabled_providers"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_opencode_v2_normalizer.py -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_opencode_v2_config' from 'app.sync'`

- [ ] **Step 3: Implement `normalize_opencode_v2_config` in `app/sync.py`**

Add the function to `app/sync.py`:

```python
def normalize_opencode_v2_config(content: dict, models: list, plugin_path: Optional[str] = None) -> dict:
    """Normalizes OpenCode configuration to native V2 schema, upgrading legacy V1 fields and syncing models."""
    if "$schema" not in content:
        content["$schema"] = "https://opencode.ai/config.json"

    # Migrate legacy "provider" map to "providers"
    if "provider" in content and isinstance(content["provider"], dict):
        legacy_provider = content.pop("provider")
        if "providers" not in content or not isinstance(content["providers"], dict):
            content["providers"] = {}
        for p_id, p_val in legacy_provider.items():
            if p_id not in content["providers"]:
                content["providers"][p_id] = p_val
    elif "providers" not in content or not isinstance(content["providers"], dict):
        content["providers"] = {}

    providers = content["providers"]
    if "litellm" not in providers or not isinstance(providers["litellm"], dict):
        providers["litellm"] = {
            "name": "LiteLLM Gateway",
            "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": "http://10.0.0.10:8448/v1"},
            "models": {}
        }
    else:
        litellm = providers["litellm"]
        litellm["package"] = "@opencode/ai/providers/openai-compatible"
        litellm.pop("npm", None)

        settings = litellm.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        if "baseURL" not in settings:
            settings["baseURL"] = "http://10.0.0.10:8448/v1"

        if "options" in litellm and isinstance(litellm["options"], dict):
            legacy_opts = litellm.pop("options")
            for k, v in legacy_opts.items():
                if k not in settings:
                    settings[k] = v
        litellm["settings"] = settings
        if "models" not in litellm or not isinstance(litellm["models"], dict):
            litellm["models"] = {}

    # Transform active LiteLLM models
    opencode_models = {}
    for m in models:
        m_name = m.get("model_name")
        if not m_name or m_name.endswith("*"):
            continue
        info = m.get("model_info", {})
        ctx_limit = info.get("max_input_tokens", 128000) or 128000
        out_limit = info.get("max_output_tokens", 8192) or 8192
        opencode_models[m_name] = {
            "name": m_name,
            "limit": {
                "context": ctx_limit,
                "output": out_limit
            }
        }

    merged_models = dict(providers["litellm"].get("models", {}))
    for m_name, m_cfg in opencode_models.items():
        if m_name in merged_models and isinstance(merged_models[m_name], dict):
            merged_models[m_name].update(m_cfg)
        else:
            merged_models[m_name] = m_cfg
    providers["litellm"]["models"] = merged_models

    # Migrate legacy "plugin" to "plugins"
    plugins = content.get("plugins")
    if not isinstance(plugins, list):
        legacy_plugin = content.pop("plugin", None)
        if isinstance(legacy_plugin, list):
            plugins = legacy_plugin
        elif isinstance(legacy_plugin, str):
            plugins = [legacy_plugin]
        else:
            plugins = []
        content["plugins"] = plugins
    else:
        legacy_plugin = content.pop("plugin", None)
        if isinstance(legacy_plugin, list):
            for p in legacy_plugin:
                if p not in plugins:
                    plugins.append(p)
        elif isinstance(legacy_plugin, str) and legacy_plugin not in plugins:
            plugins.append(legacy_plugin)

    # Optional remote plugin registration
    if plugin_path:
        norm_plugin = plugin_path.replace("\\", "/")
        if norm_plugin not in plugins:
            plugins.append(norm_plugin)

        enabled_providers = content.get("enabled_providers")
        if isinstance(enabled_providers, list) and "google-agy" not in enabled_providers:
            enabled_providers.append("google-agy")

    return content
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_opencode_v2_normalizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ai/litellm-manager/app/sync.py ai/litellm-manager/tests/test_opencode_v2_normalizer.py
git commit -m "feat(sync): implement OpenCode v2 configuration normalizer"
```

---

### Task 2: Refactor `export_opencode_config` (Local Sync)

**Files:**
- Modify: `ai/litellm-manager/app/sync.py:21-73`
- Modify: `ai/litellm-manager/tests/test_opencode_sync.py`

**Interfaces:**
- Consumes: `normalize_opencode_v2_config`
- Produces: `export_opencode_config(models: list, target_path: str = "/app/opencode_config/opencode.jsonc")`

- [ ] **Step 1: Update `tests/test_opencode_sync.py` for V2 schema**

Update the test assertions to check `content["providers"]["litellm"]`, `package: "@opencode/ai/providers/openai-compatible"`, and `settings.baseURL`:

```python
def test_export_opencode_config(tmp_path):
    target_file = tmp_path / "opencode.jsonc"
    initial_content = {
        "$schema": "https://opencode.ai/config.json",
        "providers": {
            "litellm": {
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {"baseURL": "http://10.0.0.10:8448/v1"},
                "models": {}
            }
        }
    }
    with open(target_file, "w") as f:
        json.dump(initial_content, f)

    mock_models = [
        {"model_name": "claude-3-5-sonnet", "model_info": {"max_input_tokens": 200000, "max_output_tokens": 8192}}
    ]
    export_opencode_config(mock_models, target_path=str(target_file))

    with open(target_file, "r") as f:
        result = json.load(f)

    assert "providers" in result
    assert "litellm" in result["providers"]
    litellm = result["providers"]["litellm"]
    assert litellm["package"] == "@opencode/ai/providers/openai-compatible"
    assert litellm["settings"]["baseURL"] == "http://10.0.0.10:8448/v1"
    assert "claude-3-5-sonnet" in litellm["models"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_opencode_sync.py -v`
Expected: FAIL due to `export_opencode_config` still writing legacy `provider` key.

- [ ] **Step 3: Update `export_opencode_config` in `app/sync.py`**

Refactor `export_opencode_config`:

```python
def export_opencode_config(models: list, target_path: str = "/app/opencode_config/opencode.jsonc"):
    """Sync active LiteLLM models to OpenCode configuration file using native V2 schema."""
    if not os.path.exists(target_path):
        return
    
    try:
        with open(target_path, "r") as f:
            content = json.load(f)
    except Exception as e:
        print(f"Error reading opencode config: {e}")
        return

    content = normalize_opencode_v2_config(content, models)
    
    with open(target_path, "w") as f:
        json.dump(content, f, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_opencode_sync.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ai/litellm-manager/app/sync.py ai/litellm-manager/tests/test_opencode_sync.py
git commit -m "feat(sync): update local opencode config export to native v2 format"
```

---

### Task 3: Refactor `export_remote_opencode_config` (Remote SFTP Sync)

**Files:**
- Modify: `ai/litellm-manager/app/sync.py:180-290`
- Modify: `ai/litellm-manager/tests/test_remote_opencode_sync.py`

**Interfaces:**
- Consumes: `normalize_opencode_v2_config`
- Produces: `export_remote_opencode_config(models: list) -> Dict[str, Any]`

- [ ] **Step 1: Update `tests/test_remote_opencode_sync.py` for V2 schema**

Update existing mock SFTP tests:
- `test_export_remote_opencode_config_merge_and_atomic_write`: verify `updated_data["providers"]["litellm"]`, `package`, `settings.baseURL`, and `updated_data["plugins"]`.
- Verify legacy remote configs with `"provider"` and `"plugin"` are upgraded cleanly to `"providers"` and `"plugins"`.

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_remote_opencode_sync.py -v`
Expected: FAIL due to assertions on `providers` and `plugins`.

- [ ] **Step 3: Update `export_remote_opencode_config` in `app/sync.py`**

Refactor `export_remote_opencode_config` to invoke `normalize_opencode_v2_config`:

```python
        # In export_remote_opencode_config inside the try block:
        content = normalize_opencode_v2_config(content, models, plugin_path=plugin_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_remote_opencode_sync.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ai/litellm-manager/app/sync.py ai/litellm-manager/tests/test_remote_opencode_sync.py
git commit -m "feat(sync): update remote opencode ssh sync to native v2 format"
```

---

### Task 4: Full Regression Testing & Validation

**Files:**
- Test: all test files in `ai/litellm-manager/tests/`

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All 85+ tests PASS.

- [ ] **Step 2: Commit any remaining updates if necessary**

```bash
git status
```
