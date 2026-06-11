import re

with open("main.py", "r") as f:
    content = f.read()

# 1. Update Lifespan
lifespan_old = """@asynccontextmanager
async def lifespan(app: FastAPI):
    await initial_load_models()
    yield"""

lifespan_new = """@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await refresh_app_settings()
    await initial_load_models()
    yield"""

content = content.replace(lifespan_old, lifespan_new)

# 2. Refactor constants usages
# (Careful not to replace the definitions at the top)
content = content.replace('VERTEX_CREDENTIALS, scopes=scopes)', 'get_app_setting("VERTEX_CREDENTIALS_PATH", DEFAULT_VERTEX_CREDS), scopes=scopes)')
content = content.replace('url = f"https://aiplatform.googleapis.com/v1/projects/{DEFAULT_PROJECT}/locations/{DEFAULT_LOCATION}/publishers/google/models/{model_id}"', 
                         'url = f"https://aiplatform.googleapis.com/v1/projects/{get_app_setting(\'VERTEX_PROJECT\')}/locations/{get_app_setting(\'VERTEX_LOCATION\', \'global\')}/publishers/google/models/{model_id}"')
content = content.replace('creds = service_account.Credentials.from_service_account_file(VERTEX_CREDENTIALS, scopes=scopes)', 
                         'creds = service_account.Credentials.from_service_account_file(get_app_setting("VERTEX_CREDENTIALS_PATH", DEFAULT_VERTEX_CREDS), scopes=scopes)')
content = content.replace('project=DEFAULT_PROJECT, location=DEFAULT_LOCATION', 
                         'project=get_app_setting("VERTEX_PROJECT"), location=get_app_setting("VERTEX_LOCATION", "global")')
content = content.replace('Starting Vertex discovery for {DEFAULT_LOCATION}', 'Starting Vertex discovery for {get_app_setting("VERTEX_LOCATION", "global")}')
content = content.replace('"Authorization": f"Bearer {os.environ.get(\'OPENROUTER_API_KEY\')}"', 
                         '"Authorization": f"Bearer {get_app_setting(\'OPENROUTER_API_KEY\')}"')
content = content.replace('with open(CONFIG_PATH, "r")', 'with open(get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH), "r")')
content = content.replace('with open(CONFIG_PATH, "w")', 'with open(get_app_setting("LITELLM_CONFIG", DEFAULT_CONFIG_PATH), "w")')
content = content.replace('"vertex_project": "os.environ/VERTEX_PROJECT"', '"vertex_project": get_app_setting("VERTEX_PROJECT")')
content = content.replace('"vertex_location": "global"', '"vertex_location": get_app_setting("VERTEX_LOCATION", "global")')

# Special for OpenRouter API Key in sync
content = content.replace('entry["litellm_params"]["api_key"] = "os.environ/OPENROUTER_API_KEY"', 
                         'entry["litellm_params"]["api_key"] = get_app_setting("OPENROUTER_API_KEY")')

with open("main.py", "w") as f:
    f.write(content)
print("Constants refactored.")
