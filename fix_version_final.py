import os
import re

# 1. Update VERSION file
with open("VERSION", "w") as f:
    f.write("0.1.2")

# 2. Update main.py to read VERSION file and fix build time
with open("main.py", "r") as f:
    py = f.read()

# Make sure APP_VERSION logic is clean
py = re.sub(r'APP_VERSION = os\.environ\.get\("APP_VERSION", "dev"\)', 
            'if os.path.exists("VERSION"):\n    with open("VERSION", "r") as f: APP_VERSION = f.read().strip()\nelse: APP_VERSION = "dev"', py)

with open("main.py", "w") as f:
    f.write(py)

# 3. Update index.html header
with open("app/templates/index.html", "r") as f:
    html = f.read()

html = html.replace('Version: {{ version }} | Build: {{ build_time }}', 'v{{ version }} | {{ build_time }}')

with open("app/templates/index.html", "w") as f:
    f.write(html)
