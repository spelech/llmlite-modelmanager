import re
with open("main.py", "r") as f:
    content = f.read()

# Remove all debug endpoints
content = re.sub(r"@app\.get\(\"/debug-publisher-models\"\).*?return {\"error\": str\(e\)}", "", content, flags=re.DOTALL)
content = re.sub(r"@app\.get\(\"/list-valid-models\"\).*?return {\"error\": str\(e\)}", "", content, flags=re.DOTALL)
content = re.sub(r"@app\.get\(\"/debug-skus\"\).*?return {\"error\": str\(e\)}", "", content, flags=re.DOTALL)

# Remove the print statement in fetch_vertex_publisher_models
content = content.replace('print(f"DEBUG: Found model: {model.name}"); available_ids.append(model_id)', 'available_ids.append(model_id)')

with open("main.py", "w") as f:
    f.write(content)
