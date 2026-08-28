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
