import asyncio
import os
import json
import aiosqlite

DB_PATH = "/containers/webservices/litellm/config/settings.db"
ENV_PATH = "/containers/webservices/.env"
VERTEX_CREDS_PATH = "/containers/webservices/litellm/vertex_credentials.json"

async def seed():
    if not os.path.exists(DB_PATH):
        print("Database not found at {}. Starting container first?".format(DB_PATH))
        return

    settings = {}

    # 1. Parse .env
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    if k in ["OPENROUTER_API_KEY", "VERTEX_PROJECT", "VERTEX_LOCATION", "LITELLM_CONFIG"]:
                        settings[k] = v.strip("\"' ")

    # 2. Parse Vertex JSON
    if os.path.exists(VERTEX_CREDS_PATH):
        with open(VERTEX_CREDS_PATH, "r") as f:
            settings["VERTEX_CREDENTIALS_JSON"] = f.read()

    # 3. Default Config Path if missing
    if "LITELLM_CONFIG" not in settings:
        settings["LITELLM_CONFIG"] = "/app/config/config.yaml"

    async with aiosqlite.connect(DB_PATH) as db:
        for k, v in settings.items():
            print("Seeding {}...".format(k))
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, is_secret) VALUES (?, ?, ?)",
                (k, v, 1 if "KEY" in k or "JSON" in k else 0)
            )
        await db.commit()
    print("Database seeded successfully.")

if __name__ == "__main__":
    asyncio.run(seed())
