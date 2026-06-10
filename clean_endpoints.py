with open("main.py", "r") as f:
    lines = f.readlines()

new_lines = []
skip = False
for line in lines:
    if "@app.get(\"/debug-publisher-models\")" in line or "@app.get(\"/list-valid-models\")" in line:
        skip = True
    elif line.startswith("@app.") and skip:
        # Check if it's the start of another route
        skip = False
        new_lines.append(line)
    elif skip:
        if line.strip() == "":
            skip = False
        continue
    else:
        new_lines.append(line)

with open("main.py", "w") as f:
    f.writelines(new_lines)
