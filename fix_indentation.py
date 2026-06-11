with open("main.py", "r") as f:
    content = f.read()

# Fix IndentationError in VERSION loading
old_code = """if os.path.exists("VERSION"):
    with open("VERSION", "r") as f: APP_VERSION = f.read().strip()
else: APP_VERSION = "dev\""""

# Re-match more broadly
import re
pattern = r'if os\.path\.exists\("VERSION"\):.*?else: APP_VERSION = "dev"'
replacement = """if os.path.exists("VERSION"):
    with open("VERSION", "r") as f:
        APP_VERSION = f.read().strip()
else:
    APP_VERSION = "dev\""""

content = re.sub(pattern, replacement, content, flags=re.DOTALL)

with open("main.py", "w") as f:
    f.write(content)
