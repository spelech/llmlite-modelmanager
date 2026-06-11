import re
with open("main.py", "r") as f:
    content = f.read()

# Replace the incorrect debug_skus endpoint with one that lists publisher models
debug_func = """
@app.get("/debug-publisher-models")
async def debug_publisher_models():
    token = get_google_access_token()
    if not token: return {"error": "No token"}
    # The correct URL to list models in a publisher
    url = f"https://us-central1-aiplatform.googleapis.com/v1/publishers/google/models"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return [m.get("name") for m in resp.json().get("models", [])]
            return {"error": resp.text}
        except Exception as e:
            return {"error": str(e)}
"""

# Replace the incorrect debug_skus endpoint
new_content = re.sub(r"@app.get\(\"/debug-skus\"\).*?return {\"error\": str\(e\)}", debug_func, content, flags=re.DOTALL)
with open("main.py", "w") as f:
    f.write(new_content)
