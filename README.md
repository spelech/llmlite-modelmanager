# LiteLLM Model Manager

A lightweight web-based gateway and management tool for LiteLLM.

## Features
- **Live Model Discovery**: Polls OpenRouter and Google Cloud Billing APIs for the latest available models.
- **Regional Pricing**: Specifically filters Vertex AI models by region (`us-east1`, `us-central1`, etc.) to show accurate pricing.
- **Instant Verification**: Built-in "Test" button to verify model availability and credentials through the actual LiteLLM proxy.
- **YAML Generation**: Surgically updates `config.yaml` with selected models while preserving existing settings and wildcards.

## Getting Started

### Prerequisites
- Python 3.11+
- LiteLLM Proxy running on `http://litellm:4000`

### Installation
```bash
pip install -r requirements.txt
```

### Environment Variables
- `OPENROUTER_API_KEY`: Your OpenRouter API key.
- `VERTEX_PROJECT`: Your Google Cloud Project ID.
- `VERTEX_LOCATION`: Google Cloud Region (e.g., `us-east1`).
- `VERTEX_CREDENTIALS_PATH`: Path to your service account JSON.
- `LITELLM_CONFIG`: Path to your LiteLLM `config.yaml`.
- `LITELLM_MASTER_KEY`: Your LiteLLM master key.

### Running
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Testing
Run unit tests with pytest:
```bash
pytest tests/test_api.py
```
