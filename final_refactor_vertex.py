import re

with open("main.py", "r") as f:
    content = f.read()

# Define the hardcoded specs for Gemini models
gemini_specs_code = """
GEMINI_SPECS = {
    "gemini-2.5-pro": {"ctx": 2000000, "out": 8192},
    "gemini-2.5-flash": {"ctx": 1000000, "out": 8192},
    "gemini-3.5-flash": {"ctx": 1000000, "out": 8192},
    "gemini-3.1-flash-lite": {"ctx": 1000000, "out": 8192},
    "gemini-2.0-flash-exp": {"ctx": 1048576, "out": 8192},
    "gemini-1.5-pro": {"ctx": 2097152, "out": 8192},
    "gemini-1.5-flash": {"ctx": 1048576, "out": 8192},
}
"""

# Insert GEMINI_SPECS after FALLBACK_PRICING
if "GEMINI_SPECS" not in content:
    content = re.sub(r"(FALLBACK_PRICING = {.*?})", r"\1\n" + gemini_specs_code, content, flags=re.DOTALL)

# Refactor verify_and_cache_vertex_models to be robust
new_verify_func = """async def verify_and_cache_vertex_models():
    \"\"\"Discover and merge model data using SDK and Billing API.\"\"\"
    print(f"Starting Vertex discovery for {DEFAULT_LOCATION}...")
    
    # 1. Discover canonical IDs via SDK
    model_ids = await fetch_vertex_publisher_models()
    
    # 2. Fetch Pricing from Billing API
    pricing_map = await fetch_vertex_billing_skus()
    
    models = []
    for mid in model_ids:
        # Match Pricing
        p_data = {"prompt_1m": 0.0, "completion_1m": 0.0}
        
        # Heuristic: search for best pricing match in billing keys
        # Primary search keys: mid, mid-text-input, mid-global-text-input
        search_keys = [mid, f"{mid}-text-input", f"{mid}-global-text-input", f"{mid}-input"]
        for sk in search_keys:
            if sk in pricing_map:
                p_data["prompt_1m"] = pricing_map[sk]["prompt_1m"]
                break
        
        search_keys_out = [f"{mid}-text-output", f"{mid}-global-text-output", f"{mid}-output"]
        for sk in search_keys_out:
            if sk in pricing_map:
                p_data["completion_1m"] = pricing_map[sk]["completion_1m"]
                break
        
        # Fallback to static pricing if still 0
        if p_data["prompt_1m"] == 0:
            base = "-".join(mid.split("-")[:3])
            if base in FALLBACK_PRICING:
                p_data = FALLBACK_PRICING[base]

        # Technical Specs (Hardcoded table for reliability)
        spec = GEMINI_SPECS.get(mid, {"ctx": 1000000, "out": 8192})
        # If mid contains a version number like -001, try stripping it
        if mid not in GEMINI_SPECS:
            base_id = "-".join(mid.split("-")[:3])
            spec = GEMINI_SPECS.get(base_id, spec)

        models.append({
            "id": f"vertex_ai/{mid}",
            "name": mid.replace("-", " ").title(),
            "brand": "google",
            "pricing": {
                "prompt": p_data["prompt_1m"] / 1_000_000,
                "completion": p_data["completion_1m"] / 1_000_000,
                "prompt_1m": p_data["prompt_1m"],
                "completion_1m": p_data["completion_1m"]
            },
            "context_length": spec["ctx"],
            "max_output_tokens": spec["out"],
            "capabilities": extract_capabilities("", mid)
        })

    verified_models = sorted(models, key=lambda x: x["name"])
    app_state["vx_models"] = verified_models
    app_state["last_verification_time"] = time.time()
    with open(CACHE_FILE, "w") as f:
        json.dump({"timestamp": app_state["last_verification_time"], "models": verified_models}, f)
    print(f"Vertex discovery finished. Found {len(verified_models)} models.")"""

# Replace the verify function
content = re.sub(r"async def verify_and_cache_vertex_models.*?print\(f\"Vertex discovery finished.*?\"\)", new_verify_func, content, flags=re.DOTALL)

with open("main.py", "w") as f:
    f.write(content)
