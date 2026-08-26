from typing import Dict, List
import json
from app.database import upsert_discovered_models
from app.notifications import notify_new_trending_models

def classify_model_tier(model: Dict) -> str:
    """
    Dynamically classifies a model into 'cheap', 'moderate', or 'frontier'.
    Uses pricing per 1M tokens with capability/architecture heuristics.
    """
    pricing = model.get("pricing", {})
    prompt_1m = pricing.get("prompt_1m", 0.0)
    
    mid = model.get("id", "").lower()
    name = model.get("name", "").lower()
    
    # Check explicit price bands first if available
    if prompt_1m > 0:
        if prompt_1m <= 0.30:
            return "cheap"
        elif prompt_1m <= 2.50:
            return "moderate"
        else:
            return "frontier"
            
    # Heuristic fallback if price is zero / free / unlisted
    cheap_keywords = ["lite", "mini", "micro", "nano", "flash-lite", "small", "1b", "3b", "7b", "8b", "free"]
    if any(k in mid or k in name for k in cheap_keywords):
        return "cheap"
        
    frontier_keywords = ["opus", "o3", "r1", "reasoning", "ultra", "claude-4", "gpt-5", "pro", "flagship", "deepseek-r1"]
    if any(k in mid or k in name for k in frontier_keywords):
        return "frontier"
        
    return "moderate"

async def process_and_track_discovered_models(all_models: List[Dict], notify: bool = True) -> List[Dict]:
    """
    Tags models with their computed tier, stores them in SQLite, and fires alerts for new notable models.
    """
    for m in all_models:
        m["tier"] = classify_model_tier(m)
        
    new_models = await upsert_discovered_models(all_models)
    
    if new_models and notify:
        # Filter for notable models (top popularity on OpenRouter, or Google/Anthropic/OpenAI/DeepSeek/Meta)
        notable_brands = {"google", "anthropic", "openai", "deepseek", "meta-llama", "mistralai", "x-ai", "qwen"}
        notable = [
            m for m in new_models
            if m.get("popularity", 999) <= 120 or m.get("brand", "").lower() in notable_brands or m.get("tier") == "frontier"
        ]
        if notable:
            await notify_new_trending_models(notable)
            
    return new_models
