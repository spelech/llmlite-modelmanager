import re

with open("main.py", "r") as f:
    py = f.read()

# 1. Fix sync_models to use "global" as literal string for vertex_location
py = re.sub(r'\"vertex_location\": \"os\.environ/VERTEX_LOCATION\"', '\"vertex_location\": \"global\"', py)

# 2. Fix test_model to handle "global" correctly in SDK
# (We already have DEFAULT_LOCATION = global, so it should work if SDK handles it)

with open("main.py", "w") as f:
    f.write(py)
