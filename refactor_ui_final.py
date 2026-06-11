import re

with open("app/templates/index.html", "r") as f:
    html = f.read()

# 1. Remove brand-group headers from model list
html = re.sub(r'{% set current_brand = "" %}', '', html)
html = re.sub(r'{% if m\.brand != current_brand %}.*?{% endif %}', '', html, flags=re.DOTALL)
html = re.sub(r'// Hide/Show brand headers.*?\}\);', '', html, flags=re.DOTALL)

# 2. Refactor Settings Modal to group by provider
new_modal_content = """
            <h2>Manager Configuration</h2>
            <form id="settingsForm" class="settings-grid">
                <section>
                    <h3 style="font-size: 0.8em; color: var(--accent); text-transform: uppercase; margin-bottom: 10px; border-bottom: 1px solid var(--border);">General Settings</h3>
                    <div class="filter-group">
                        <span class="filter-label">LiteLLM Config Path</span>
                        <input type="text" name="LITELLM_CONFIG" id="setting_CONFIG_PATH" placeholder="/app/config/config.yaml">
                    </div>
                </section>

                <section style="margin-top: 15px;">
                    <h3 style="font-size: 0.8em; color: var(--accent); text-transform: uppercase; margin-bottom: 10px; border-bottom: 1px solid var(--border);">OpenRouter</h3>
                    <div class="filter-group">
                        <span class="filter-label">API Key</span>
                        <div style="display: flex; gap: 10px;">
                            <input type="password" name="OPENROUTER_API_KEY" id="setting_OR_KEY" placeholder="sk-or-v1-..." style="flex-grow: 1;">
                            <button type="button" class="btn-refresh" onclick="togglePassword('setting_OR_KEY')">👁️</button>
                        </div>
                    </div>
                </section>

                <section style="margin-top: 15px;">
                    <h3 style="font-size: 0.8em; color: var(--accent); text-transform: uppercase; margin-bottom: 10px; border-bottom: 1px solid var(--border);">Vertex AI</h3>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                        <div class="filter-group">
                            <span class="filter-label">Project ID</span>
                            <input type="text" name="VERTEX_PROJECT" id="setting_VX_PROJ" placeholder="your-project-id">
                        </div>
                        <div class="filter-group">
                            <span class="filter-label">Location</span>
                            <input type="text" name="VERTEX_LOCATION" id="setting_VX_LOC" placeholder="global">
                        </div>
                    </div>
                    <div class="filter-group" style="margin-top: 10px;">
                        <span class="filter-label">Service Account JSON</span>
                        <textarea name="VERTEX_CREDENTIALS_JSON" id="setting_VX_JSON" placeholder='{ "type": "service_account", ... }' rows="6" style="background: var(--bg-input); border: 1px solid var(--border); color: var(--text-main); padding: 8px 12px; border-radius: 4px; font-family: monospace; font-size: 0.8em; resize: vertical;"></textarea>
                    </div>
                </section>

                <div style="margin-top: 20px; display: flex; gap: 15px; justify-content: flex-end;">
                    <button type="button" class="btn-refresh" onclick="closeSettings()">Cancel</button>
                    <button type="submit" class="btn-sync" style="padding: 10px 25px; background: var(--accent); color: white; border-radius: 4px; font-weight: bold;">Save & Refresh</button>
                </div>
            </form>
"""

html = re.sub(r'<h2>Manager Configuration</h2>.*?<div style="margin-top: 10px; display: flex; gap: 15px; justify-content: flex-end;">.*?</div>', new_modal_content, html, flags=re.DOTALL)

# Adjust modal width for grouped layout
html = html.replace('width: 550px;', 'width: 650px;')

with open("app/templates/index.html", "w") as f:
    f.write(html)
print("UI Grouping Refactored.")
