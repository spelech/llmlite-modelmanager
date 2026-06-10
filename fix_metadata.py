import sys
with open("main.py", "r") as f:
    content = f.read()

func = """async def fetch_vertex_model_metadata(model_id: str) -> Dict[str, int]:
    \"\"\"Fetch model metadata from Vertex AI API.\"\"\"
    token = get_google_access_token()
    if not token:
        print("DEBUG: No token")
        return {}

    # Vertex model ID format needs to be 'publishers/google/models/{MODEL_ID}'
    # We have 'vertex_ai/{short_id}'
    short_id = model_id.split("/")[-1]
    url = f"https://{DEFAULT_LOCATION}-aiplatform.googleapis.com/v1/publishers/google/models/{short_id}"
    print(f"DEBUG: URL={url}")

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            print(f"DEBUG: Status={resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "max_input_tokens": int(data.get("inputTokenLimit", 0)),
                    "max_output_tokens": int(data.get("outputTokenLimit", 0))
                }
            else:
                print(f"DEBUG: Response={resp.text}")
        except Exception as e:
            print(f"Exception in fetch_vertex_model_metadata: {e}")
    return {}"""

# Find the function and replace it
import re
new_content = re.sub(r"async def fetch_vertex_model_metadata.*?return {}", func, content, flags=re.DOTALL)
with open("main.py", "w") as f:
    f.write(new_content)
