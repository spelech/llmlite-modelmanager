import re

with open("main.py", "r") as f:
    content = f.read()

# Ensure we don't duplicate headers in config.yaml
# The sync_models function should update only the model_list part and preserve others safely.
new_sync_func = """@app.post("/sync")
async def sync_models(request: Request):
    form_data = await request.form()
    selected_ids = form_data.getlist("models")
    all_models = app_state["or_models"] + app_state["vx_models"]
    model_map = {m["id"]: m for m in all_models}
    
    config_path = get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH)
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
    
    new_model_list = []
    for mid in selected_ids:
        m_data = model_map.get(mid, {})
        pricing = m_data.get("pricing", {})
        
        entry = {
            "model_name": mid.split("/")[-1],
            "litellm_params": {"model": mid},
            "model_info": {
                "id": mid,
                "input_cost_per_token": pricing.get("prompt", 0),
                "output_cost_per_token": pricing.get("completion", 0),
                "max_input_tokens": m_data.get("max_input_tokens", 0),
                "max_output_tokens": m_data.get("max_output_tokens", 0),
                "capabilities": m_data.get("capabilities", {}),
                "brand": m_data.get("brand", "other")
            }
        }
        
        if mid.startswith("openrouter/"):
            entry["litellm_params"]["api_key"] = get_app_setting("OPENROUTER_API_KEY")
        elif mid.startswith("vertex_ai/"):
            entry["litellm_params"].update({
                "vertex_project": get_app_setting("VERTEX_PROJECT"),
                "vertex_location": get_app_setting("VERTEX_LOCATION", "global"),
                "vertex_credentials": "/app/vertex_credentials.json"
            })
            # Character-based pricing for Gemini
            entry["model_info"]["input_cost_per_character"] = pricing.get("prompt", 0)
            entry["model_info"]["output_cost_per_character"] = pricing.get("completion", 0)
            
        new_model_list.append(entry)
    
    # Filter out existing models from model_list that are NOT wildcards
    # and replace with our new list.
    existing_list = config.get("model_list", [])
    wildcards = [m for m in existing_list if "*" in m.get("model_name", "")]
    
    config["model_list"] = new_model_list + wildcards
    
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
        
    return {"status": "success", "updated_models": len(new_model_list)}"""

# Replace the sync function
pattern = r"@app\.post\(\"/sync\"\).*?return {\"status\": \"success\", \"updated_models\": len\(new_model_list\)}"
content = re.sub(pattern, new_sync_func, content, flags=re.DOTALL)

with open("main.py", "w") as f:
    f.write(content)
print("Sync logic updated.")
