"""Minimal health check script for Azure OpenAI deployment.

Behavior:
1. If AZURE_OPENAI_API_KEY is set -> use API key authentication via AzureOpenAI client.
2. Else -> fall back to Entra ID (DefaultAzureCredential) and bearer token provider.

Environment variables honored (with safe defaults / placeholders):
  AZURE_OPENAI_ENDPOINT (required)
  AZURE_OPENAI_GPT_DEPLOYMENT or AZURE_OPENAI_DEPLOYMENT (model deployment name)
  AZURE_OPENAI_API_KEY (optional for key-based auth)
  AZURE_OPENAI_API_VERSION (optional – default used if unset)

Outputs a single line starting with HEALTH_OK or HEALTH_FAIL for easy CI parsing.
"""

import os
import sys
import json
from pathlib import Path
from typing import Tuple
from dotenv import load_dotenv

DEFAULT_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

# Model capability map to safely tailor parameters (avoid unsupported ones for reasoning models like gpt-5)
MODEL_CAPS = {
    # Reasoning GPT-5 family (example deployment names). Adjust keys to match your deployment names if they differ.
    "gpt-5": {
        "supports_sampling": False,  # temperature/top_p not allowed
        "token_param": "max_completion_tokens",
        "supports_reasoning_effort": True,
        "api": "chat"
    },
    "gpt-5-mini": {
        "supports_sampling": False,
        "token_param": "max_completion_tokens",
        "supports_reasoning_effort": True,
        "api": "chat"
    },
    # Default catch‑all (typical non-reasoning chat model like gpt-4o)
    "default": {
        "supports_sampling": True,
        "token_param": "max_tokens",  # legacy / non-reasoning
        "supports_reasoning_effort": False,
        "api": "chat"
    }
}


def _get_config() -> Tuple[str, str, str]:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT_URL")
    deployment = (
        os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or os.getenv("OPENAI_DEPLOYMENT")
        or "gpt-4o"  # sensible default placeholder
    )
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION)
    if not endpoint:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT not set.")
    return endpoint, deployment, api_version


def _build_params(deployment: str, question: str, token_limit: int = 32):
    caps = MODEL_CAPS.get(deployment, MODEL_CAPS.get(deployment.lower(), MODEL_CAPS["default"]))
    # Fallback if user names deployment differently (case-insensitive)
    if caps is MODEL_CAPS["default"]:
        # Try matching by prefix (e.g., deployment name like 'gpt-5-preview')
        lowered = deployment.lower()
        if lowered.startswith("gpt-5"):
            caps = MODEL_CAPS["gpt-5"]
    params = {
        "model": deployment,
        "messages": [
            {"role": "system", "content": "You are a concise health check assistant."},
            {"role": "user", "content": question},
        ],
    }
    params[caps["token_param"]] = token_limit
    if caps.get("supports_reasoning_effort"):
        params["reasoning_effort"] = os.getenv("AZURE_OPENAI_REASONING_EFFORT", "minimal")
    if caps.get("supports_sampling"):
        # Only include temperature if supported; allow override via env else mild default for non-reasoning
        temperature_env = os.getenv("AZURE_OPENAI_TEMPERATURE")
        if temperature_env:
            try:
                params["temperature"] = float(temperature_env)
            except ValueError:
                pass
        else:
            params["temperature"] = 0.2  # small non-zero to avoid some SDK defaults if user wants variety
    return params, caps


def _call_with_api_key(endpoint: str, deployment: str, api_version: str, question: str) -> str:
    from openai import AzureOpenAI  # local import to keep failure surface minimal
    client = AzureOpenAI(
        api_version=api_version,
        azure_endpoint=endpoint,
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    )
    params, caps = _build_params(deployment, question)
    try:
        resp = client.chat.completions.create(**params)
    except Exception as e:
        # Adaptive retry: remove temperature if present & retry once
        if "Unsupported" in str(e) and "temperature" in params:
            params.pop("temperature", None)
            resp = client.chat.completions.create(**params)
        else:
            raise
    return resp.choices[0].message.content.strip()


def _call_with_default_credential(endpoint: str, deployment: str, api_version: str, question: str) -> str:
    # Mirrors pattern used elsewhere in repo (prompts_engineering_llmlingua.initialize_ai_models)
    import openai
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")
    openai.api_type = "azure"
    openai.azure_ad_token_provider = token_provider
    openai.azure_endpoint = endpoint
    openai.api_version = api_version

    params, caps = _build_params(deployment, question)
    try:
        resp = openai.chat.completions.create(**params)
    except Exception as e:
        # Adaptive cleanup for reasoning model constraints
        mutated = False
        if "Unsupported parameter" in str(e):
            # Remove unsupported generation params dynamically
            for bad in ("temperature", "top_p", "presence_penalty", "frequency_penalty", "max_tokens"):
                if bad in params:
                    params.pop(bad, None)
                    mutated = True
        if "Unsupported value" in str(e) and "temperature" in str(e):
            params.pop("temperature", None)
            mutated = True
        if mutated:
            resp = openai.chat.completions.create(**params)
        else:
            raise
    return resp.choices[0].message.content.strip()


def _load_parent_env():
    """Load a .env file from the project root (one level up) if present.

    This lets the script run from inside the subfolder while reusing the
    shared environment configuration. Existing environment variables are NOT
    overridden (override=False) to respect container / CI injected secrets.
    """
    project_root_env = Path(__file__).resolve().parents[1] / '.env'
    if project_root_env.exists():
        load_dotenv(project_root_env, override=False)


def main():
    # Ensure parent .env variables are loaded before resolving config
    _load_parent_env()
    try:
        endpoint, deployment, api_version = _get_config()
        question = "Return the single word OK."  # deterministic minimal token usage
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        if api_key:
            answer = _call_with_api_key(endpoint, deployment, api_version, question)
            auth_mode = "api_key"
        else:
            answer = _call_with_default_credential(endpoint, deployment, api_version, question)
            auth_mode = "default_credential"

        status = "HEALTH_OK" if "OK" in answer.upper() else "HEALTH_UNCERTAIN"
        print(json.dumps({
            "status": status,
            "auth_mode": auth_mode,
            "endpoint": endpoint,
            "deployment": deployment,
            "api_version": api_version,
            "answer": answer
        }))
        if status != "HEALTH_OK":
            sys.exit(2)
    except Exception as e:
        print(json.dumps({
            "status": "HEALTH_FAIL",
            "error": str(e.__class__.__name__),
            "message": str(e)
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()