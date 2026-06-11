import re

with open("main.py", "r") as f:
    content = f.read()

# Update get_openrouter_models sorting
content = content.replace('return sorted(models, key=lambda x: x["name"])', 
                         'return sorted(models, key=lambda x: (x["brand"], x["name"]))')

with open("main.py", "w") as f:
    f.write(content)
