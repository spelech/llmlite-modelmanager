# OpenCode v2 Configuration Sync Specification

## 1. Overview
With the release of OpenCode v2, the configuration schema has been revised with several key changes:
- Pluralization of maps: `provider` becomes `providers`, `plugin` becomes `plugins`.
- Custom provider package specification: `npm: "@ai-sdk/openai-compatible"` is replaced by native package `package: "@opencode/ai/providers/openai-compatible"`.
- Provider options and endpoints: `options.baseURL` moves to `settings.baseURL`.
- Model definitions: Models and their context/output token limits reside under `providers.<provider_id>.models.<model_name>`.

This specification defines how `litellm-manager` synchronizes LiteLLM models to both local and remote OpenCode configurations, ensuring full compatibility with OpenCode v2 while seamlessly upgrading existing v1 configuration files in-place without data loss.

## 2. Architecture & Normalization

A unified normalizer function `normalize_opencode_v2_config(content: dict, models: list, plugin_path: Optional[str] = None) -> dict` in `app/sync.py` encapsulates all schema migration and model synchronization rules:

### 2.1 Provider Migration & Setup
1. **Key Pluralization**:
   - If `content` contains legacy `provider`:
     - If `providers` does not exist: rename `provider` to `providers`.
     - If `providers` already exists: merge any items from `provider` into `providers` without overwriting existing `providers` keys, then remove `provider`.
   - If neither exists: initialize `providers = {}`.

2. **LiteLLM Provider Structure**:
   - Ensure `providers["litellm"]` exists.
   - Set or preserve display name: `name: "LiteLLM Gateway"`.
   - Update runtime package:
     - Set `"package": "@opencode/ai/providers/openai-compatible"`.
     - Remove legacy `"npm"` key if present.
   - Migrate Settings:
     - Ensure `"settings"` dictionary exists.
     - Default `"baseURL": "http://10.0.0.10:8448/v1"` if not already configured.
     - If legacy `"options"` exists:
       - Move all keys from `"options"` (e.g. `baseURL`, `apiKey`, custom options) into `"settings"` if not already present in `"settings"`.
       - Delete the legacy `"options"` key.

3. **Active Model Synchronization**:
   - Active LiteLLM models (excluding wildcard models ending in `*`) are transformed into:
     ```json
     {
       "name": "<model_name>",
       "limit": {
         "context": <max_input_tokens or 128000>,
         "output": <max_output_tokens or 8192>
       }
     }
     ```
   - Existing model entries in `providers["litellm"]["models"]` are updated cleanly with the latest token limits, preserving any custom user fields (such as custom variants or settings).

### 2.2 Plugin Migration & Registration
1. **Key Pluralization**:
   - If `content` contains legacy `plugin`:
     - If `plugins` does not exist: convert `plugin` to a list (if not already) and set as `plugins`.
     - If `plugins` already exists: merge any missing items from `plugin` into `plugins`.
     - Remove legacy `plugin` key.
2. **Remote Plugin Injection**:
   - If `plugin_path` is supplied:
     - Normalize path backslashes to forward slashes: `norm_plugin = plugin_path.replace("\\", "/")`.
     - Append `norm_plugin` to `plugins` if not already present.
     - If `enabled_providers` list is present in the configuration, ensure `"google-agy"` is included.

### 2.3 Preserved Settings
- Top-level `$schema` is set to `"https://opencode.ai/config.json"`.
- All other top-level keys (`model`, `default_agent`, `permissions`, `experimental`, `mcp`, `compaction`, etc.) remain completely untouched.

## 3. Sync Execution Endpoints

### 3.1 Local Sync (`export_opencode_config`)
- Target: `/app/opencode_config/opencode.jsonc` (configurable via `target_path`).
- If target file does not exist, return immediately without error.
- Read JSON/JSONC, invoke `normalize_opencode_v2_config(content, models)`, and write back atomically/cleanly with `indent=2`.

### 3.2 Remote SSH/SFTP Sync (`export_remote_opencode_config`)
- Target: `OPENCODE_REMOTE_CONFIG_PATH` on remote host via SFTP.
- If remote file does not exist (`FileNotFoundError`), initialize with base template:
  ```json
  {
    "$schema": "https://opencode.ai/config.json",
    "providers": {}
  }
  ```
- If remote file exists, create backup copy `<config_path>.bak`.
- Apply `normalize_opencode_v2_config(content, models, plugin_path=plugin_path)`.
- Atomically write to `<config_path>.tmp` and rename to `<config_path>`.

## 4. Testing & Verification

1. **Local Sync Tests (`tests/test_opencode_sync.py`)**:
   - Test generating fresh v2 configuration.
   - Test in-place upgrade of existing v1 configuration (`provider` -> `providers`, `npm` -> `package`, `options` -> `settings`).
   - Test model merging and preservation of custom user models/properties.

2. **Remote Sync Tests (`tests/test_remote_opencode_sync.py`)**:
   - Test remote export with v2 provider structure.
   - Test remote plugin registration using `plugins` array (upgrading legacy `plugin`).
   - Test backup creation and atomic file rename on remote SFTP server.

3. **Regression Tests**:
   - Run full pytest test suite across `litellm-manager`.

## 5. Versioning
- Increment `VERSION` from `0.14.0` to `0.15.0`.
