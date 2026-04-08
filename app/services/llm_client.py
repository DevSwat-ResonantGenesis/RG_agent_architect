"""
RG Agent Architect — LLM Client

Handles all LLM API calls for the orchestrator ReAct loop.
Supports Groq (primary) and OpenAI (fallback) with key rotation.
Twin architecture: the orchestrator IS the high-reasoning layer.
"""
import json
import logging
import random
from typing import Optional

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

# Track which keys hit rate limits
_rate_limited_keys: set[str] = set()


async def call_llm(
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    provider: str = "groq",
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    user_api_keys: Optional[dict[str, str]] = None,
) -> dict:
    """Call LLM with tool-use support. Returns the raw API response dict.

    Args:
        messages: Chat messages (system + user + assistant + tool)
        tools: OpenAI-format tool schemas
        provider: "groq" or "openai"
        model: Model name override
        temperature: Sampling temperature
        max_tokens: Max response tokens
        user_api_keys: User-provided API keys (override platform keys)

    Returns:
        Raw API response dict with choices[0].message
    """
    if provider == "openai":
        return await _call_openai(messages, tools, model, temperature, max_tokens, user_api_keys)
    return await _call_groq(messages, tools, model, temperature, max_tokens, user_api_keys)


async def _call_groq(
    messages: list[dict],
    tools: Optional[list[dict]],
    model: Optional[str],
    temperature: float,
    max_tokens: int,
    user_api_keys: Optional[dict[str, str]],
) -> dict:
    """Call Groq API with automatic key rotation on rate limits."""
    model = model or settings.DEFAULT_MODEL

    # Build key pool: user key first, then platform keys
    key_pool = []
    if user_api_keys and user_api_keys.get("groq"):
        key_pool.append(user_api_keys["groq"])
    for k in settings.groq_keys():
        if k not in _rate_limited_keys:
            key_pool.append(k)
    # Add rate-limited keys as last resort
    for k in settings.groq_keys():
        if k in _rate_limited_keys and k not in key_pool:
            key_pool.append(k)

    if not key_pool:
        raise ValueError("No Groq API keys configured")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    last_error = None
    for api_key in key_pool:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if resp.status_code == 200:
                    _rate_limited_keys.discard(api_key)
                    return resp.json()

                if resp.status_code == 429:
                    _rate_limited_keys.add(api_key)
                    logger.warning(f"[LLM] Groq key rate-limited, rotating...")
                    last_error = f"Rate limited (429)"
                    continue

                last_error = f"Groq {resp.status_code}: {resp.text[:200]}"
                logger.error(f"[LLM] {last_error}")

        except httpx.TimeoutException:
            last_error = "Groq timeout"
            logger.warning(f"[LLM] Groq timeout, trying next key...")
            continue
        except Exception as e:
            last_error = str(e)
            logger.error(f"[LLM] Groq error: {e}")
            continue

    # All Groq keys failed — fallback to OpenAI if available
    if settings.OPENAI_API_KEY:
        logger.info("[LLM] All Groq keys failed, falling back to OpenAI")
        return await _call_openai(messages, tools, None, temperature, max_tokens, user_api_keys)

    raise RuntimeError(f"All LLM calls failed. Last error: {last_error}")


async def _call_openai(
    messages: list[dict],
    tools: Optional[list[dict]],
    model: Optional[str],
    temperature: float,
    max_tokens: int,
    user_api_keys: Optional[dict[str, str]],
) -> dict:
    """Call OpenAI API."""
    model = model or settings.REASONING_MODEL
    api_key = (user_api_keys or {}).get("openai") or settings.OPENAI_API_KEY

    if not api_key:
        raise ValueError("No OpenAI API key configured")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            OPENAI_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

        if resp.status_code == 200:
            return resp.json()

        raise RuntimeError(f"OpenAI {resp.status_code}: {resp.text[:300]}")
