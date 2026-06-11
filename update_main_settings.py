import re

with open("main.py", "r") as f:
    content = f.read()

# 1. Add helper to write Vertex JSON to file
helper_code = """
def update_vertex_creds_file():
    \"\"\"Write Vertex JSON from settings to file for GCP SDK use.\"\"\"
    json_content = get_app_setting("VERTEX_CREDENTIALS_JSON")
    if json_content:
        try:
            # Validate JSON
            json.loads(json_content)
            # Write to default path
            with open(DEFAULT_VERTEX_CREDS, "w") as f:
                f.write(json_content)
            print(f"Updated Vertex credentials file at {DEFAULT_VERTEX_CREDS}")
        except Exception as e:
            print(f"Error writing Vertex credentials JSON: {e}")
"""

# Insert before initial_load_models
content = content.replace("async def initial_load_models():", helper_code + "\nasync def initial_load_models():")

# 2. Update lifespan to call this helper
lifespan_old = "await refresh_app_settings()"
lifespan_new = "await refresh_app_settings()\n    update_vertex_creds_file()"
content = content.replace(lifespan_old, lifespan_new)

# 3. Update api_update_settings to call this helper
api_old = "await refresh_app_settings()"
api_new = "await refresh_app_settings()\n    update_vertex_creds_file()"
# Careful with indentation/context
content = re.sub(r"(async def api_update_settings.*?await refresh_app_settings\(\))", r"\1\n    update_vertex_creds_file()", content, flags=re.DOTALL)

with open("main.py", "w") as f:
    f.write(content)
print("main.py updated to handle Vertex JSON.")
