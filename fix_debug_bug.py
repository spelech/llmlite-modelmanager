with open("main.py", "r") as f:
    content = f.read()

# Fix the bug by moving the print AFTER short_id definition
old_line = 'print(f"DEBUG: name={model_name}, id={short_id}"); short_id = model_name.lower().replace(" ", "-")'
new_line = 'short_id = model_name.lower().replace(" ", "-"); print(f"DEBUG: name={model_name}, id={short_id}")'
content = content.replace(old_line, new_line)

with open("main.py", "w") as f:
    f.write(content)
