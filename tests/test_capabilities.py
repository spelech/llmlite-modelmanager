import pytest
from app.capabilities import extract_capabilities, GEMINI_SPECS, FALLBACK_PRICING

def test_gemini_37_flash_capabilities():
    caps = extract_capabilities(description="", model_id="gemini-3.7-flash")
    assert caps["text_in"] is True
    assert caps["text_out"] is True
    assert caps["image_in"] is True
    assert caps["audio_in"] is True
    assert caps["video_in"] is True
    assert caps["pdf_in"] is True
    assert caps["function_calling"] is True
    assert caps["streaming"] is True
    assert caps["image_out"] is False

def test_gemini_37_flash_specs():
    spec = GEMINI_SPECS.get("gemini-3.7-flash")
    assert spec is not None
    assert spec["ctx"] == 1000000
    assert spec["out"] == 65536

def test_gemini_pro_specs():
    spec = GEMINI_SPECS.get("gemini-3.7-pro")
    assert spec is not None
    assert spec["ctx"] == 2000000
    assert spec["out"] == 65536

def test_imagen_capabilities():
    caps = extract_capabilities(description="Image generation model", model_id="imagen-3.0-generate-002")
    assert caps["text_in"] is True
    assert caps["text_out"] is False
    assert caps["image_out"] is True
    assert caps["function_calling"] is False

def test_embedding_capabilities():
    caps = extract_capabilities(description="Text embedding", model_id="gemini-embedding-2")
    assert caps["text_in"] is True
    assert caps["text_out"] is False
    assert caps["function_calling"] is False
