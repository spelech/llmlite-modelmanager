import re

with open("main.py", "r") as f:
    content = f.read()

# Remove old/duplicated Vertex functions
content = re.sub(r"async def fetch_vertex_model_metadata.*?return list\(models_data\.values\(\)\)", "TEMP_PLACEHOLDER_SKU", content, flags=re.DOTALL)
content = re.sub(r"async def fetch_vertex_publisher_models.*?return False", "TEMP_PLACEHOLDER_PUB", content, flags=re.DOTALL)
content = re.sub(r"async def verify_and_cache_vertex_models.*?functional models\.\"\)", "TEMP_PLACEHOLDER_VERIFY", content, flags=re.DOTALL)

# New Implementation
new_metadata_func = """async def fetch_vertex_model_metadata(model_id: str) -> Dict[str, int]:
    \"\"\"Fetch technical limits (tokens) for a canonical model ID.\"\"\"
    token = get_google_access_token()
    if not token: return {}
    
    # model_id expected as 'gemini-1.5-pro'
    url = f"https://aiplatform.googleapis.com/v1/projects/{DEFAULT_PROJECT}/locations/{DEFAULT_LOCATION}/publishers/google/models/{model_id}"
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "max_input_tokens": int(data.get("inputTokenLimit", 0)),
                    "max_output_tokens": int(data.get("outputTokenLimit", 0))
                }
        except: pass
    return {}"""

new_billing_func = """async def fetch_vertex_billing_skus() -> Dict[str, Dict]:
    \"\"\"Fetch pricing data for Gemini models from the Billing API.\"\"\"
    token = get_google_access_token()
    if not token: return {}

    try:
        url = "https://cloudbilling.googleapis.com/v1/services/C7E2-9256-1C43/skus"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200: return {}
            
            skus = resp.json().get("skus", [])
            pricing_map = {} # model_base_name -> pricing
            
            for s in skus:
                desc = s.get("description", "")
                if "Gemini" not in desc: continue
                if any(x in desc for x in ["High Priority", "Provisioned", "Commitment", "Reserved"]): continue

                # Extract base name like 'Gemini 1.5 Pro'
                name_parts = desc.split(" - ")[0].split(" GA ")[0].strip()
                model_key = name_parts.lower().replace(" ", "-")
                
                if model_key not in pricing_map:
                    pricing_map[model_key] = {"prompt_1m": 0.0, "completion_1m": 0.0}
                
                pricing_info = s.get("pricingInfo", [{}])[0].get("pricingExpression", {})
                rate = pricing_info.get("tieredRates", [{}])[0].get("unitPrice", {})
                price_usd = float(rate.get("units", 0)) + (float(rate.get("nanos", 0)) / 1e9)
                
                if "Input" in desc: pricing_map[model_key]["prompt_1m"] = price_usd * 1_000_000
                elif "Output" in desc: pricing_map[model_key]["completion_1m"] = price_usd * 1_000_000
            
            return pricing_map
    except: return {}"""

new_pub_func = """async def fetch_vertex_publisher_models() -> List[str]:
    \"\"\"List all available foundation models in the region using GenAI SDK.\"\"\"
    try:
        from google import genai
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
        creds = service_account.Credentials.from_service_account_file(VERTEX_CREDENTIALS, scopes=scopes)
        client = genai.Client(vertexai=True, project=DEFAULT_PROJECT, location=DEFAULT_LOCATION, credentials=creds)
        
        ids = []
        for model in client.models.list():
            mid = model.name.split("/")[-1]
            if "gemini" in mid.lower(): ids.append(mid)
        return list(set(ids))
    except Exception as e:
        print(f"SDK Discovery Error: {e}")
        return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"]"""

new_verify_func = """async def verify_and_cache_vertex_models():
    \"\"\"Discover and merge model data without proxy dependency.\"\"\"
    print(f"Starting Vertex discovery for {DEFAULT_LOCATION}...")
    
    # 1. Discover Models
    model_ids = await fetch_vertex_publisher_models()
    
    # 2. Fetch Pricing & Metadata in parallel
    pricing_map = await fetch_vertex_billing_skus()
    
    models = []
    for mid in model_ids:
        # Technical Metadata
        meta = await fetch_vertex_model_metadata(mid)
        
        # Match Pricing (Heuristic)
        pricing = {"prompt_1m": 0.0, "completion_1m": 0.0}
        # Try direct match
        if mid in pricing_map: pricing = pricing_map[mid]
        else:
            # Try partial match (e.g. gemini-1.5-pro-002 -> gemini-1.5-pro)
            for k, p in pricing_map.items():
                if k in mid:
                    pricing = p
                    break
        
        # Fallback to static if still 0
        if pricing["prompt_1m"] == 0:
            base = "-".join(mid.split("-")[:3])
            if base in FALLBACK_PRICING:
                pricing = FALLBACK_PRICING[base]

        models.append({
            "id": f"vertex_ai/{mid}",
            "name": mid.replace("-", " ").title(),
            "brand": "google",
            "pricing": {
                "prompt": pricing["prompt_1m"] / 1_000_000,
                "completion": pricing["completion_1m"] / 1_000_000,
                "prompt_1m": pricing["prompt_1m"],
                "completion_1m": pricing["completion_1m"]
            },
            "context_length": meta.get("max_input_tokens", 0),
            "max_output_tokens": meta.get("max_output_tokens", 0),
            "capabilities": extract_capabilities("", mid)
        })

    verified_models = sorted(models, key=lambda x: x["name"])
    app_state["vx_models"] = verified_models
    app_state["last_verification_time"] = time.time()
    with open(CACHE_FILE, "w") as f:
        json.dump({"timestamp": app_state["last_verification_time"], "models": verified_models}, f)
    print(f"Vertex discovery finished. Found {len(verified_models)} models.")"""

# Combine into main.py
content = content.replace("TEMP_PLACEHOLDER_SKU", new_metadata_func + "\n\n" + new_billing_func)
content = content.replace("TEMP_PLACEHOLDER_PUB", new_pub_func)
content = content.replace("TEMP_PLACEHOLDER_VERIFY", new_verify_func)

# Fix imports if needed
if "from typing import List, Dict" not in content:
    content = "from typing import List, Dict\n" + content

with open("main.py", "w") as f:
    f.write(content)
