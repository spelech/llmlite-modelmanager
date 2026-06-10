import httpx
from google.oauth2 import service_account
from google.auth.transport.requests import Request as AuthRequest

def get_google_access_token():
    try:
        creds = service_account.Credentials.from_service_account_file("/containers/webservices/litellm/vertex_credentials.json", scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(AuthRequest())
        return creds.token
    except Exception as e:
        print(f"Error: {e}")
        return None

token = get_google_access_token()
if token:
    url = "https://aiplatform.googleapis.com/v1/projects/poised-receiver-492017-j6/locations/us-central1/publishers/google/models"
    headers = {"Authorization": f"Bearer {token}"}
    resp = httpx.get(url, headers=headers)
    if resp.status_code == 200:
        models = resp.json().get("models", [])
        for m in models:
            name = m.get("name", "")
            if "gemini" in name.lower():
                print(name)
    else:
        print(f"Status: {resp.status_code}, Response: {resp.text}")
