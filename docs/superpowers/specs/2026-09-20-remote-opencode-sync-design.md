# Remote OpenCode SSH Sync & Plugin Integration Design

## Objective
Enable `litellm-manager` to safely synchronize active models and token limits directly to an OpenCode configuration file located on a remote host (e.g., Windows workstation) over SSH/SFTP, while optionally registering a locally cloned instance of `opencode-agy-auth` and enabling the `google-agy` provider. The implementation avoids hardcoding or committing any user-specific or machine-specific IPs, paths, usernames, or credentials.

## Architecture

### 1. Configuration & Privacy
All remote sync parameters are managed dynamically through the SQLite database (`modelmanager-settings.db`) and configurable via the Settings modal UI:
- `OPENCODE_REMOTE_ENABLED`: Boolean (`"true"` / `"false"`), defaults to `"false"`.
- `OPENCODE_REMOTE_HOST`: Hostname or IP address (e.g. `10.0.0.21`).
- `OPENCODE_REMOTE_PORT`: SSH port (defaults to `22`).
- `OPENCODE_REMOTE_USER`: SSH username (e.g. `Alias`).
- `OPENCODE_REMOTE_KEY`: Private SSH Key (RSA, Ed25519) stored directly in SQLite settings. No container volume mounts or file-system dependencies required.
- `OPENCODE_REMOTE_KEY_PASSPHRASE`: Optional key passphrase.
- `OPENCODE_REMOTE_CONFIG_PATH`: Absolute target path on the remote host (e.g. `C:/Users/Alias/.config/opencode/opencode.json`).
- `OPENCODE_REMOTE_PLUGIN_PATH`: Optional local plugin path on the remote host (e.g. `C:/Users/Alias/repos/opencode-agy-auth`).

### 2. Remote SSH/SFTP Client
- Uses `paramiko` in-memory key loading (`paramiko.Ed25519Key.from_private_key(io.StringIO(...))` / `paramiko.RSAKey.from_private_key(...)`).
- Establishes an SFTP connection over SSH.
- Test endpoint: `POST /api/settings/test-remote-opencode` verifies connectivity, authentication, and directory accessibility before enabling.

### 3. Synchronization Flow & Safety
During model sync (`sync_models_internal`):
1. **Local Sync**: LiteLLM `config.yaml`, local OpenCode (`/app/opencode_config/opencode.jsonc`), and LibreChat targets update as usual.
2. **Remote Check**: If `OPENCODE_REMOTE_ENABLED` is not `"true"` or host/user/config_path is blank, remote sync is skipped cleanly.
3. **Remote Read & Backup**:
   - SFTP reads existing `opencode.json` (or `.jsonc`).
   - SFTP writes a backup copy `<config_path>.bak` (and optional timestamped backup).
4. **Surgical Merge**:
   - Preserves all existing root fields (`mcp`, `model`, `small_model`, etc.).
   - Preserves `provider.litellm.options` (e.g., `baseURL`, `apiKey`).
   - Updates `provider.litellm.models` with current active models, context limits, and output limits.
   - If `OPENCODE_REMOTE_PLUGIN_PATH` is provided:
     - Normalizes path slashes (replaces `\` with `/`).
     - Appends to `plugin` list if not already present.
     - Adds `"google-agy"` to `enabled_providers` if `enabled_providers` exists.
5. **Atomic Write**:
   - Writes new content to `<config_path>.tmp`.
   - Renames `<config_path>.tmp` to `<config_path>` via SFTP.
6. **Error Isolation**:
   - If remote SSH fails or the remote host is offline, local sync remains successful. A descriptive warning is returned and notification dispatched.

### 4. Remote Machine Setup (One-Time Bootstrap)
- Clone `spelech/opencode-agy-auth` to a local non-NFS drive (e.g. `C:\Users\Alias\repos\opencode-agy-auth`).
- Run `npm install` and `npm run build`.
