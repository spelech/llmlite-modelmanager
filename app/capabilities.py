from typing import Dict, List, Optional

# Fallback pricing table for Gemini models
FALLBACK_PRICING = {
    "gemini-3.7-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-3.7-pro": {"prompt_1m": 1.25, "completion_1m": 3.75},
    "gemini-3.5-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-3.5-pro": {"prompt_1m": 1.25, "completion_1m": 3.75},
    "gemini-3.1-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-3.1-flash-lite": {"prompt_1m": 0.03, "completion_1m": 0.10},
    "gemini-3.1-pro": {"prompt_1m": 1.25, "completion_1m": 3.75},
    "gemini-3-pro": {"prompt_1m": 1.25, "completion_1m": 3.75},
    "gemini-3-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-2.5-flash": {"prompt_1m": 0.10, "completion_1m": 0.40},
    "gemini-2.5-pro": {"prompt_1m": 1.25, "completion_1m": 3.75},
    "gemini-2.0-flash": {"prompt_1m": 0.10, "completion_1m": 0.40},
    "gemini-2.0-flash-exp": {"prompt_1m": 0.10, "completion_1m": 0.40},
    "gemini-1.5-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-1.5-pro": {"prompt_1m": 1.25, "completion_1m": 5.00},
    "gemini-embedding": {"prompt_1m": 0.02, "completion_1m": 0.0},
    "gemini-embedding-2": {"prompt_1m": 0.02, "completion_1m": 0.0},
}

# Technical specification defaults for Gemini models
GEMINI_SPECS = {
    "gemini-3.7-flash": {"ctx": 1000000, "out": 65536},
    "gemini-3.7-pro": {"ctx": 2000000, "out": 65536},
    "gemini-3.5-flash": {"ctx": 1000000, "out": 65536},
    "gemini-3.5-pro": {"ctx": 2000000, "out": 65536},
    "gemini-3.1-flash": {"ctx": 1000000, "out": 65536},
    "gemini-3.1-flash-lite": {"ctx": 1000000, "out": 65536},
    "gemini-3.1-pro": {"ctx": 2000000, "out": 65536},
    "gemini-3-pro": {"ctx": 2000000, "out": 65536},
    "gemini-3-flash": {"ctx": 1000000, "out": 65536},
    "gemini-2.5-flash": {"ctx": 1000000, "out": 65536},
    "gemini-2.5-pro": {"ctx": 2000000, "out": 65536},
    "gemini-2.0-flash": {"ctx": 1000000, "out": 65536},
    "gemini-2.0-flash-exp": {"ctx": 1000000, "out": 65536},
    "gemini-1.5-flash": {"ctx": 1000000, "out": 8192},
    "gemini-1.5-pro": {"ctx": 2000000, "out": 8192},
}

def extract_capabilities(description: str = "", model_id: str = "", supported_methods: Optional[List[str]] = None) -> Dict[str, bool]:
    """
    Capability extraction for input/output modalities and features.
    Accurately tags multimodal Gemini models, vision LLMs, code/tool agents, and media generators.
    """
    desc_low = (description or "").lower()
    mid_low = (model_id or "").lower()

    def match(keywords):
        return any(k in desc_low or k in mid_low for k in keywords)

    is_gemini = "gemini" in mid_low or "gemini" in desc_low
    is_imagen = "imagen" in mid_low or "imagen" in desc_low
    is_embedding = "embedding" in mid_low or "embed" in desc_low or (supported_methods and "embedContent" in supported_methods and len(supported_methods) == 1)

    if is_imagen:
        return {
            "text_in": True,
            "text_out": False,
            "image_in": match(["edit", "inpaint", "image-to-image"]),
            "image_out": True,
            "audio_in": False,
            "audio_out": False,
            "video_in": False,
            "video_out": False,
            "pdf_in": False,
            "function_calling": False,
            "streaming": False
        }

    if is_embedding:
        return {
            "text_in": True,
            "text_out": False,
            "image_in": match(["multimodal", "image"]),
            "image_out": False,
            "audio_in": False,
            "audio_out": False,
            "video_in": match(["multimodal", "video"]),
            "video_out": False,
            "pdf_in": False,
            "function_calling": False,
            "streaming": False
        }

    if is_gemini:
        # Ground-truth: All Gemini generation models natively support text, image, audio, video, PDF, function calling, streaming
        return {
            "text_in": True,
            "text_out": True,
            "image_in": True,
            "image_out": False,
            "audio_in": True,
            "audio_out": match(["bidi", "voice", "live", "tts"]),
            "video_in": True,
            "video_out": False,
            "pdf_in": True,
            "function_calling": True,
            "streaming": True
        }

    # Universal heuristics for Claude, OpenAI, DeepSeek, Qwen, LLaMA, Mistral, etc.
    is_claude = "claude" in mid_low
    is_openai = any(k in mid_low for k in ["gpt-4", "gpt-5", "o1", "o3", "o4", "chatgpt"])
    
    return {
        "text_in": True,
        "text_out": True,
        "image_in": match(["vision", "image", "multimodal", "flash", "pro", "vl", "pixtral", "omni", "gpt-4o", "claude-3"]),
        "image_out": match(["dall-e", "generator", "draw", "flux", "midjourney", "sdxl"]),
        "audio_in": match(["audio", "speech", "whisper", "voice", "omni"]),
        "audio_out": match(["tts", "text-to-speech", "audio-out", "voice-out"]),
        "video_in": match(["video", "multimodal", "omni"]),
        "video_out": match(["video-gen", "sora", "veo", "runway", "kling"]),
        "pdf_in": is_claude or match(["pdf", "document", "multimodal"]),
        "function_calling": is_claude or is_openai or match(["function", "tool", "agent", "instruct", "chat", "command-r", "qwen", "mistral", "deepseek"]),
        "streaming": True
    }

FALLBACK_GEMINI_BENCHMARKS = {
    "gemini-3.7-flash": {"coding": 76.1, "intelligence": 56.0, "agentic": 45.1},
    "gemini-3.7-pro": {"coding": 82.0, "intelligence": 64.5, "agentic": 54.0},
    "gemini-2.5-flash": {"coding": 73.0, "intelligence": 55.0, "agentic": 44.0},
    "gemini-2.5-pro": {"coding": 78.5, "intelligence": 62.0, "agentic": 51.2},
    "gemini-2.0-flash": {"coding": 71.0, "intelligence": 53.0, "agentic": 42.0},
    "gemini-1.5-pro": {"coding": 68.0, "intelligence": 54.0, "agentic": 42.0},
    "gemini-1.5-flash": {"coding": 60.0, "intelligence": 48.0, "agentic": 38.0}
}

def extract_benchmarks(benchmarks_data: Optional[Dict]) -> Dict[str, Optional[float]]:
    """
    Extract normalized 0-100 benchmark scores (coding, intelligence, agentic)
    from OpenRouter benchmarks payload (e.g. Artificial Analysis indices).
    """
    res = {
        "coding": None,
        "intelligence": None,
        "agentic": None
    }
    if not benchmarks_data or not isinstance(benchmarks_data, dict):
        return res
    
    aa = benchmarks_data.get("artificial_analysis")
    if not aa or not isinstance(aa, dict):
        return res
        
    if aa.get("coding_index") is not None:
        try:
            res["coding"] = round(float(aa["coding_index"]), 1)
        except (ValueError, TypeError):
            pass
    if aa.get("intelligence_index") is not None:
        try:
            res["intelligence"] = round(float(aa["intelligence_index"]), 1)
        except (ValueError, TypeError):
            pass
    if aa.get("agentic_index") is not None:
        try:
            res["agentic"] = round(float(aa["agentic_index"]), 1)
        except (ValueError, TypeError):
            pass
    return res

def resolve_benchmarks_for_model(model_id: str, or_models: Optional[List[Dict]] = None) -> Dict[str, Optional[float]]:
    """
    Find matching benchmark scores for a model (e.g. Vertex model) from OpenRouter models or fallbacks.
    """
    base_slug = model_id.split("/")[-1].lower()
    
    if or_models:
        for om in or_models:
            om_id = om.get("id", "").lower().replace("openrouter/", "")
            om_slug = om_id.split("/")[-1]
            if om_slug == base_slug or om_id == f"google/{base_slug}":
                b = om.get("benchmarks", {})
                if b and any(v is not None for v in b.values()):
                    return {
                        "coding": b.get("coding"),
                        "intelligence": b.get("intelligence"),
                        "agentic": b.get("agentic")
                    }

    # Check fallback lookup
    for key, benchmarks in FALLBACK_GEMINI_BENCHMARKS.items():
        if key in base_slug or base_slug.startswith(key):
            return {
                "coding": benchmarks.get("coding"),
                "intelligence": benchmarks.get("intelligence"),
                "agentic": benchmarks.get("agentic")
            }
            
    return {
        "coding": None,
        "intelligence": None,
        "agentic": None
    }

