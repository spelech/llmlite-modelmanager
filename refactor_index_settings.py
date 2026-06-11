import re

with open("app/templates/index.html", "r") as f:
    content = f.read()

# 1. Add Modal CSS
modal_css = """
        /* Modal Styles */
        .modal {
            display: none;
            position: fixed;
            z-index: 2000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.7);
            backdrop-filter: blur(5px);
        }
        .modal-content {
            background-color: var(--bg-card);
            margin: 5% auto;
            padding: 30px;
            border: 1px solid var(--border);
            width: 550px;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.5);
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        .modal-content h2 { margin: 0; font-size: 1.5em; color: var(--accent); }
        .settings-grid { display: flex; flex-direction: column; gap: 15px; }
"""

# Insert CSS before </style>
content = content.replace("</style>", modal_css + "\n    </style>")

# 2. Add Settings Button to Header
settings_btn = '<button type="button" class="btn-refresh" onclick="openSettings()">Settings</button>'
content = content.replace('<div class="header-version">', settings_btn + '\n            <div class="header-version">')

# 3. Add Modal HTML before </body>
modal_html = """
    <!-- Settings Modal -->
    <div id="settingsModal" class="modal">
        <div class="modal-content">
            <h2>Manager Configuration</h2>
            <form id="settingsForm" class="settings-grid">
                <div class="filter-group">
                    <span class="filter-label">OpenRouter API Key</span>
                    <input type="password" name="OPENROUTER_API_KEY" id="setting_OR_KEY" placeholder="sk-or-v1-...">
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
                    <span class="filter-label">Vertex Credentials Path</span>
                    <input type="text" name="VERTEX_CREDENTIALS_PATH" id="setting_VX_CREDS" placeholder="/app/vertex_credentials.json">
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
content = content.replace("</body>", modal_html + "\n</body>")

# 4. Add JS functions
settings_js = """
        async function openSettings() {
            try {
                const resp = await fetch('/api/settings');
                const settings = await resp.json();
                
                document.getElementById('setting_OR_KEY').value = settings.OPENROUTER_API_KEY || '';
                document.getElementById('setting_VX_PROJ').value = settings.VERTEX_PROJECT || '';
                document.getElementById('setting_VX_LOC').value = settings.VERTEX_LOCATION || 'global';
                document.getElementById('setting_VX_CREDS').value = settings.VERTEX_CREDENTIALS_PATH || '';
                document.getElementById('setting_CONFIG_PATH').value = settings.LITELLM_CONFIG || '';
                
                document.getElementById('settingsModal').style.display = 'block';
            } catch (e) { alert('Failed to load settings'); }
        }

        function closeSettings() {
            document.getElementById('settingsModal').style.display = 'none';
        }

        document.getElementById('settingsForm').onsubmit = async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData.entries());
            
            try {
                const resp = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                if (resp.ok) {
                    closeSettings();
                    alert('Settings saved. Refreshing models...');
                    window.location.reload();
                }
            } catch (e) { alert('Error saving settings'); }
        };
"""

# Insert JS before applyAllFilters
content = content.replace("function applyAllFilters() {", settings_js + "\n        function applyAllFilters() {")

with open("app/templates/index.html", "w") as f:
    f.write(content)
