with open("main.py", "r") as f:
    lines = f.readlines()

new_lines = []
skip = False
for line in lines:
    if line.strip() == "GEMINI_SPECS = {":
        if any("GEMINI_SPECS" in l for l in new_lines):
            skip = True
            continue
    if skip and line.strip() == "}":
        skip = False
        continue
    if skip:
        continue
    if line.strip() == ",": # remove that lone comma
        continue
    new_lines.append(line)

with open("main.py", "w") as f:
    f.writelines(new_lines)
