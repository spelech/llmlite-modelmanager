import re
with open("main.py", "r") as f:
    content = f.read()

debug_func = """
@app.get("/debug-skus")
async def debug_skus():
    token = get_google_access_token()
    if not token: return {"error": "No token"}
    url = "https://cloudbilling.googleapis.com/v1/services/C7E2-9256-1C43/skus"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            skus = resp.json().get("skus", [])
            return [s.get("description") for s in skus if "Gemini" in s.get("description", "")]
        except Exception as e:
            return {"error": str(e)}
"""

new_content = re.sub(r"@app.post\(\"/sync\"\)", debug_func + "\n@app.post(\"/sync\")", content)
with open("main.py", "w") as f:
    f.write(new_content)
