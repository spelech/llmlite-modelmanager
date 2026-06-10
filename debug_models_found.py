import re
with open("main.py", "r") as f:
    content = f.read()

# Add logging
new_content = content.replace('available_ids.append(model_id)', 'print(f"DEBUG: Found model: {model.name}"); available_ids.append(model_id)')

with open("main.py", "w") as f:
    f.write(new_content)
