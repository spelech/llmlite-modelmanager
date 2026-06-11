import re

with open("app/templates/index.html", "r") as f:
    html = f.read()

# Remove stray header/style blocks that might be at the bottom
html = re.sub(r"</div>\s+<header>.*?</script>", "</div>\n    <script>", html, flags=re.DOTALL)

# Ensure the header is correctly showing Version: vX.Y.Z
html = html.replace("v{{ version }} | {{ build_time }}", "v{{ version }} | {{ build_time }}")

with open("app/templates/index.html", "w") as f:
    f.write(html)

with open("main.py", "r") as f:
    py = f.read()

# Fix OpenRouter test API key usage: it might be using sk-or-... directly which is good, 
# but let's check the Authorization header format.
# Standard is "Bearer sk-or-v1-..."
# I am currently using: f"Bearer {os.environ.get('OPENROUTER_API_KEY')}"

# Let's add a check for the project location and project ID.
# If some models only work on 'global', we might need to handle that.
# But for now, let's just fix the UI.
with open("main.py", "w") as f:
    f.write(py)
