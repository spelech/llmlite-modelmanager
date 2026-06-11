import re

with open("main.py", "r") as f:
    content = f.read()

settings_api = """
@app.get("/api/settings")
async def api_get_settings():
    return await get_all_settings()

@app.post("/api/settings")
async def api_update_settings(data: Dict[str, str]):
    for k, v in data.items():
        await set_setting(k, v)
    await refresh_app_settings()
    return {"status": "success"}
"""

# Insert before @app.get("/api/config")
content = content.replace('@app.get("/api/config")', settings_api + "\n@app.get(\"/api/config\")")

with open("main.py", "w") as f:
    f.write(content)
