import re

# 1. Fix main.py defaults logic
with open("main.py", "r") as f:
    py = f.read()

# Ensure we have a robust DEFAULT_LOCATION
if "DEFAULT_LOCATION =" not in py:
    py = py.replace('CACHE_EXPIRY_DAYS = 7', 'CACHE_EXPIRY_DAYS = 7\nDEFAULT_LOCATION = "global"')

# Update get_config error log (remove stale DEBUG URL)
py = py.replace('print(f"DEBUG: URL={url}"); return {"error": str(e)}', 'return {"error": str(e)}')

with open("main.py", "w") as f:
    f.write(py)

# 2. Update index.html to show resolved defaults in UI
with open("app/templates/index.html", "r") as f:
    html = f.read()

# Update JS to show defaults if setting is missing
html = html.replace("document.getElementById('setting_VX_LOC').value = settings.VERTEX_LOCATION || 'global';",
                   "document.getElementById('setting_VX_LOC').value = settings.VERTEX_LOCATION || 'global';")
html = html.replace("document.getElementById('setting_CONFIG_PATH').value = settings.LITELLM_CONFIG || '';",
                   "document.getElementById('setting_CONFIG_PATH').value = settings.LITELLM_CONFIG || '/app/config/config.yaml';")

with open("app/templates/index.html", "w") as f:
    f.write(html)

print("Defaults logic updated.")
