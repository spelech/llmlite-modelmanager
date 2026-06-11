import re

# 1. main.py Refactor
with open("main.py", "r") as f:
    py = f.read()

# Refactor MASTER_KEY definition
py = py.replace('MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-local-wileyriley-gateway-12345")', 
                'MASTER_KEY_DEFAULT = "sk-local-wileyriley-gateway-12345"')

# Refactor usages of MASTER_KEY
py = py.replace('Bearer {MASTER_KEY}', 'Bearer {get_app_setting("LITELLM_MASTER_KEY", MASTER_KEY_DEFAULT)}')

with open("main.py", "w") as f:
    f.write(py)

# 2. index.html Refactor
with open("app/templates/index.html", "r") as f:
    html = f.read()

# Add Master Key field to modal
new_field = """                <div class="filter-group">
                    <span class="filter-label">LiteLLM Master Key</span>
                    <input type="password" name="LITELLM_MASTER_KEY" id="setting_MASTER_KEY" placeholder="sk-...">
                </div>"""

# Insert before CONFIG_PATH field
html = html.replace('<input type="text" name="LITELLM_CONFIG" id="setting_CONFIG_PATH"', 
                   new_field + '\n                <div class="filter-group">\n                    <span class="filter-label">LiteLLM Config Path</span>\n                    <input type="text" name="LITELLM_CONFIG" id="setting_CONFIG_PATH"')

# Update JS to populate it
html = html.replace('document.getElementById(\'setting_CONFIG_PATH\').value = settings.LITELLM_CONFIG || \'\';',
                   'document.getElementById(\'setting_CONFIG_PATH\').value = settings.LITELLM_CONFIG || \'\';\n                document.getElementById(\'setting_MASTER_KEY\').value = settings.LITELLM_MASTER_KEY || \'\';')

with open("app/templates/index.html", "w") as f:
    f.write(html)

print("Master Key added to settings.")
