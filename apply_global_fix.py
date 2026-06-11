import re

with open("main.py", "r") as f:
    py = f.read()

# 1. Update DEFAULT_LOCATION constant
py = re.sub(r'DEFAULT_LOCATION = os\.environ\.get\("VERTEX_LOCATION", "us-central1"\)', 
            'DEFAULT_LOCATION = os.environ.get("VERTEX_LOCATION", "global")', py)

# 2. Update fetch_vertex_model_metadata to use the specific regional URL if global fails, 
# or just use the global-compatible base URL.
# The user mentioned location="global" in the SDK.

# 3. Update verify_and_cache_vertex_models to explicitly mention it's discovering on global
py = py.replace('print(f"Starting Vertex discovery for {DEFAULT_LOCATION}...")', 
                'print(f"Starting Vertex discovery for {DEFAULT_LOCATION} (Universal Mode)...")')

# 4. Update the sync_models function to use 'global' in the generated config
# find the line: "vertex_location": "os.environ/VERTEX_LOCATION"
# and change it to "global" if we want to force it, or ensure the env var is set.
# The user seems to want this as the standard.

with open("main.py", "w") as f:
    f.write(py)
print("Global location fix applied to main.py")
