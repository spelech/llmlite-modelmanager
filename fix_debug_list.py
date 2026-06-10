import re
with open("main.py", "r") as f:
    content = f.read()

endpoint = """
@app.get("/list-valid-models")
async def list_valid_models():
    token = get_google_access_token()
    if not token: return {"error": "No token"}
    url = f"https://aiplatform.googleapis.com/v1/projects/{DEFAULT_PROJECT}/locations/{DEFAULT_LOCATION}/publishers/google/models"
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

# Insert before /api/models
new_content = re.sub(r"@app\.get\(\"/api/models\"\)", endpoint + "\n@app.get(\"/api/models\")", content)
with open("main.py", "w") as f:
    f.write(new_content)
