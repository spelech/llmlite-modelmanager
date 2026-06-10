with open("app/templates/index.html", "r") as f:
    content = f.read()

# 1. Ensure the footer button is removed if it was accidentally kept
content = content.replace('<button type="button" class="btn-refresh" onclick="forceRefresh()">Force Refresh Metadata</button>', '')

# 2. Fix potential double form/header issues
# (Checking for redundant blocks)

with open("app/templates/index.html", "w") as f:
    f.write(content)
