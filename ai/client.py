"""
Unified AI client — switches between Anthropic Claude and Ollama
based on AI_PROVIDER setting.

Usage:
    from ai.client import chat
    response = chat(system="...", user="...")
"""
import json
import logging
import re

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


def chat(system: str, user: str, max_tokens: int = 1500) -> str:
    """
    Send a chat completion request to the configured AI provider.
    Returns the text response, or raises RuntimeError if unavailable.
    """
    provider = settings.ai_provider.lower()

    if provider == "anthropic":
        return _chat_anthropic(system, user, max_tokens)
    elif provider == "ollama":
        return _chat_ollama(system, user, max_tokens)
    else:
        raise RuntimeError(f"AI provider not configured (AI_PROVIDER={settings.ai_provider!r})")


# ── Anthropic ──────────────────────────────────────────────────────────────────

def _chat_anthropic(system: str, user: str, max_tokens: int) -> str:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    import anthropic as _anthropic

    client = _anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return message.content[0].text.strip()


# ── Ollama ─────────────────────────────────────────────────────────────────────

def _chat_ollama(system: str, user: str, max_tokens: int) -> str:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    # num_predict é ignorado por modelos cloud (ex: kimi-k2.5:cloud) — omitir
    # para não causar resposta vazia. Só inclui para modelos locais.
    is_cloud_model = ":cloud" in settings.ollama_model or settings.ollama_model.endswith(":cloud")
    options = {} if is_cloud_model else {"num_predict": max_tokens}

    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if options:
        payload["options"] = options
    headers = {}
    if settings.ollama_api_key:
        headers["Authorization"] = f"Bearer {settings.ollama_api_key}"

    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=120)
        r.raise_for_status()
        data = r.json()
        return data["message"]["content"].strip()
    except httpx.ConnectError:
        raise RuntimeError(
            f"Ollama não está rodando em {settings.ollama_base_url}. "
            "Inicie com: ollama serve"
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Ollama API error: {e.response.text}")


def is_available() -> bool:
    """Check if the configured AI provider is reachable."""
    provider = settings.ai_provider.lower()
    if provider == "anthropic":
        return bool(settings.anthropic_api_key)
    if provider == "ollama":
        try:
            r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False
    return False


def provider_info() -> dict:
    """Return info about the current AI provider for logging/health checks."""
    provider = settings.ai_provider.lower()
    if provider == "anthropic":
        return {
            "provider": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "available": bool(settings.anthropic_api_key),
        }
    if provider == "ollama":
        return {
            "provider": "ollama",
            "model": settings.ollama_model,
            "base_url": settings.ollama_base_url,
            "available": is_available(),
        }
    return {"provider": "none", "available": False}
