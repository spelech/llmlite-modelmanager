import re

with open("main.py", "r") as f:
    content = f.read()

new_test_func = """@app.post("/test")
async def test_model(model_id: str = Form(...)):
    \"\"\"Test model availability directly via provider APIs (bypassing proxy).\"\"\"
    try:
        if model_id.startswith("vertex_ai/"):
            short_id = model_id.split("/")[-1]
            # Use the SDK to test availability directly via Vertex AI
            scopes = ['https://www.googleapis.com/auth/cloud-platform']
            creds = service_account.Credentials.from_service_account_file(VERTEX_CREDENTIALS, scopes=scopes)
            client = genai.Client(vertexai=True, project=DEFAULT_PROJECT, location=DEFAULT_LOCATION, credentials=creds)
            
            try:
                # Use generate_content with a tiny prompt as a true connectivity test
                # This verifies both existence and credentials
                resp = client.models.generate_content(model=short_id, contents="ping")
                return {"status": "success", "response": resp.text}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        elif model_id.startswith("openrouter/"):
            # Test OpenRouter directly via its API
            or_id = model_id.replace("openrouter/", "")
            headers = {
                "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY')}",
                "Content-Type": "application/json"
            }
            payload = {"model": or_id, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 10}
            async with httpx.AsyncClient() as client:
                resp = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
                if resp.status_code == 200:
                    return {"status": "success", "response": resp.json()["choices"][0]["message"]["content"]}
                return {"status": "error", "message": resp.text}
                
        return {"status": "error", "message": "Unknown provider prefix"}
    except Exception as e:
        return {"status": "error", "message": str(e)}"""

# Replace the old test endpoint
pattern = r"@app\.post\(\"/test\"\).*?return {\"status\": \"error\", \"message\": str\(e\)}"
content = re.sub(pattern, new_test_func, content, flags=re.DOTALL)

with open("main.py", "w") as f:
    f.write(content)
