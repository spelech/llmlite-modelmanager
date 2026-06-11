import re
with open("main.py", "r") as f:
    content = f.read()

# Filter models in the response
new_endpoint = """
@app.get("/debug-publisher-models")
async def debug_publisher_models():
    token = get_google_access_token()
    if not token: return {"error": "No token"}
    url = f"https://aiplatform.googleapis.com/v1/projects/{DEFAULT_PROJECT}/locations/{DEFAULT_LOCATION}/publishers/google/models"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                # Return only models with "gemini" in their name
                return [m.get("name") for m in resp.json().get("models", []) if "gemini" in m.get("name", "").lower()]
            return {"error": resp.text}
        except Exception as e:
            return {"error": str(e)}
"""

# Replace the existing endpoint
# Use re.sub with flags=re.DOTALL to match multiline
new_content = re.sub(r"@app\.get\(\"/debug-publisher-models\"\).*?return {\"error\": str\(e\)}", new_endpoint, content, flags=re.DOTALL)

with open("main.py", "w") as f:
    f.write(new_content)
