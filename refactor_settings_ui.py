import re

with open("app/templates/index.html", "r") as f:
    content = f.read()

# 1. Update modal HTML
new_modal = """
    <!-- Settings Modal -->
    <div id="settingsModal" class="modal">
        <div class="modal-content">
            <h2>Manager Configuration</h2>
            <form id="settingsForm" class="settings-grid">
                <div class="filter-group">
                    <span class="filter-label">OpenRouter API Key</span>
                    <div style="display: flex; gap: 10px;">
                        <input type="password" name="OPENROUTER_API_KEY" id="setting_OR_KEY" placeholder="sk-or-v1-..." style="flex-grow: 1;">
                        <button type="button" class="btn-refresh" onclick="togglePassword('setting_OR_KEY')">👁️</button>
                    </div>
                </div>
                <div class="filter-group">
                    <span class="filter-label">LiteLLM Master Key</span>
                    <div style="display: flex; gap: 10px;">
                        <input type="password" name="LITELLM_MASTER_KEY" id="setting_MASTER_KEY" placeholder="sk-..." style="flex-grow: 1;">
                        <button type="button" class="btn-refresh" onclick="togglePassword('setting_MASTER_KEY')">👁️</button>
                    </div>
                </div>
                <div class="filter-group">
                    <span class="filter-label">Vertex Project ID</span>
                    <input type="text" name="VERTEX_PROJECT" id="setting_VX_PROJ" placeholder="your-project-id">
                </div>
                <div class="filter-group">
                    <span class="filter-label">Vertex Location</span>
                    <input type="text" name="VERTEX_LOCATION" id="setting_VX_LOC" placeholder="global">
                </div>
                <div class="filter-group">
                    <span class="filter-label">Vertex Service Account JSON</span>
                    <textarea name="VERTEX_CREDENTIALS_JSON" id="setting_VX_JSON" placeholder='{ "type": "service_account", ... }' rows="5" style="background: var(--bg-input); border: 1px solid var(--border); color: var(--text-main); padding: 8px 12px; border-radius: 4px; font-family: monospace; font-size: 0.8em;"></textarea>
                </div>
                <div class="filter-group">
                    <span class="filter-label">LiteLLM Config Path</span>
                    <input type="text" name="LITELLM_CONFIG" id="setting_CONFIG_PATH" placeholder="/app/config/config.yaml">
                </div>
                <div style="margin-top: 10px; display: flex; gap: 15px; justify-content: flex-end;">
                    <button type="button" class="btn-refresh" onclick="closeSettings()">Cancel</button>
                    <button type="submit" class="btn-sync" style="padding: 10px 25px;">Save & Refresh</button>
                </div>
            </form>
        </div>
    </div>
"""

# Replace old modal
content = re.sub(r"<!-- Settings Modal -->.*?</div>\s+</div>", new_modal, content, flags=re.DOTALL)

# 2. Update JS functions
settings_js = """
        function togglePassword(id) {
            const input = document.getElementById(id);
            input.type = input.type === 'password' ? 'text' : 'password';
        }

        async function openSettings() {
            try {
                const resp = await fetch('/api/settings');
                const settings = await resp.json();
                
                document.getElementById('setting_OR_KEY').value = settings.OPENROUTER_API_KEY || '';
                document.getElementById('setting_VX_PROJ').value = settings.VERTEX_PROJECT || '';
                document.getElementById('setting_VX_LOC').value = settings.VERTEX_LOCATION || 'global';
                document.getElementById('setting_VX_JSON').value = settings.VERTEX_CREDENTIALS_JSON || '';
                document.getElementById('setting_CONFIG_PATH').value = settings.LITELLM_CONFIG || '';
                document.getElementById('setting_MASTER_KEY').value = settings.LITELLM_MASTER_KEY || '';
                
                document.getElementById('settingsModal').style.display = 'block';
            } catch (e) { alert('Failed to load settings'); }
        }
"""

# Replace openSettings and add togglePassword
content = re.sub(r"async function openSettings\(\) {.*?}\s+function closeSettings\(\)", settings_js + "\n        function closeSettings()", content, flags=re.DOTALL)

with open("app/templates/index.html", "w") as f:
    f.write(content)
print("Settings UI refactored.")
