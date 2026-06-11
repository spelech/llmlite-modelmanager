import re

with open("main.py", "r") as f:
    py = f.read()

# 1. Update the DEFAULT_LOCATION and ensure it is used everywhere.
# (I already set it to global, but let me check sync_models)
py = re.sub(r'\"vertex_location\": \"os\.environ/VERTEX_LOCATION\"', '\"vertex_location\": \"global\"', py)

# 2. Update fetch_vertex_model_metadata to use the global-compatible base URL.
# The URL should be: f"https://{DEFAULT_LOCATION}-aiplatform.googleapis.com/v1/projects/{DEFAULT_PROJECT}/locations/{DEFAULT_LOCATION}/publishers/google/models/{model_id}"
# But if it is global, it is often just 'https://aiplatform.googleapis.com/v1/...'

with open("main.py", "w") as f:
    f.write(py)
