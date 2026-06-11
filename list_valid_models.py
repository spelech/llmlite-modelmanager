from google.oauth2 import service_account
from google.auth.transport.requests import Request as AuthRequest
import httpx
import json

def get_token():
    creds = service_account.Credentials.from_service_account_file(
        "/containers/webservices/litellm/vertex_credentials.json", 
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(AuthRequest())
    return creds.token

def list_models():
    token = get_token()
    # Replace with your actual project/location
    url = "https://aiplatform.googleapis.com/v1/projects/poised-receiver-492017-j6/locations/us-central1/publishers/google/models"
    headers = {"Authorization": f"Bearer {token}"}
    
    with httpx.Client() as client:
        resp = client.get(url, headers=headers)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            for m in models:
                print(m.get("name"))
        else:
            print(f"Error: {resp.status_code} - {resp.text}")

list_models()
