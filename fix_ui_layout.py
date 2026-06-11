import re

with open("app/templates/index.html", "r") as f:
    content = f.read()

# 1. Extract the misplaced header and style
header_pattern = r"<header>.*?</style>"
header_match = re.search(header_pattern, content, flags=re.DOTALL)
if header_match:
    header_content = header_match.group(0)
    # Remove it from the bottom
    content = content.replace(header_content, "")
    
    # 2. Insert header correctly after <body> start
    content = content.replace("<body>", "<body>\n    " + header_content)

# 3. Remove any remaining redundant footer/version info if present
# (We already removed the div in a previous step, but let's be sure)

with open("app/templates/index.html", "w") as f:
    f.write(content)
print("UI Layout fixed.")
