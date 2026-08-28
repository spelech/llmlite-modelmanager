import httpx
from typing import List, Dict
from app.capabilities import extract_capabilities
from app.discovery import classify_model_tier

async def get_openrouter_models() -> List[Dict]:
    """Fetch and format OpenRouter models with capabilities and tiers."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://openrouter.ai/api/v1/models?sort=most-popular")
            if resp.status_code != 200:
                return []
            
            models = []
            for idx, m in enumerate(resp.json().get("data", [])):
                brand = m['id'].split("/")[0] if "/" in m['id'] else "other"
                pricing_dict = {
                    "prompt": float(m.get("pricing", {}).get("prompt", 0)),
                    "completion": float(m.get("pricing", {}).get("completion", 0)),
                    "prompt_1m": float(m.get("pricing", {}).get("prompt", 0)) * 1_000_000,
                    "completion_1m": float(m.get("pricing", {}).get("completion", 0)) * 1_000_000
                }
                model_item = {
                    "id": f"openrouter/{m['id']}",
                    "name": m.get("name", m["id"]),
                    "brand": brand,
                    "popularity": idx,
                    "pricing": pricing_dict,
                    "max_input_tokens": m.get("context_length", 0),
                    "max_output_tokens": m.get("top_provider", {}).get("max_completion_tokens", 0),
                    "capabilities": extract_capabilities(m.get("description", ""), m["id"])
                }
                model_item["tier"] = classify_model_tier(model_item)
                models.append(model_item)
            return models
    except Exception as e:
        print(f"Error fetching OpenRouter: {e}")
        return []
