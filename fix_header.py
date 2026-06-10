import re

with open("app/templates/index.html", "r") as f:
    content = f.read()

# Fix header version display
content = content.replace("v{{ version }} | {{ build_time }}", "Version: {{ version }} | Build: {{ build_time }}")

# Ensure the header is correctly placed and not duplicated
# (I already did this but maybe I missed a spot)

with open("app/templates/index.html", "w") as f:
    f.write(content)
