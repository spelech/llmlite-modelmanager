import re

with open("main.py", "r") as f:
    py = f.read()

# Remove MASTER_KEY_DEFAULT and its usage
py = re.sub(r'MASTER_KEY_DEFAULT = ".*?"', '', py)
# (It s already not used elsewhere)

with open("main.py", "w") as f:
    f.write(py)

with open("app/templates/index.html", "r") as f:
    html = f.read()

# Remove from Modal
modal_pattern = r'<div class="filter-group">\s+<span class="filter-label">LiteLLM Master Key</span>.*?</div>\s+</div>'
html = re.sub(modal_pattern, '', html, flags=re.DOTALL)

# Remove from JS
html = html.replace("document.getElementById('setting_MASTER_KEY').value = settings.LITELLM_MASTER_KEY || '';", "")

with open("app/templates/index.html", "w") as f:
    f.write(html)
