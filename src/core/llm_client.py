"""LLM Client — Groq + OpenAI with key rotation and fallback"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.core.config import GROQ_API_KEY, GROQ_API_KEY_2, OPENAI_API_KEY

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

DEFAULT_MODEL = "llama-3.3-70b-versatile"
FAST_MODEL = "llama-3.1-8b-instant"
REASONING_MODEL = "gpt-4o"


def _groq_keys() -> List[str]:
    keys = []
    for raw in (GROQ_API_KEY, GROQ_API_KEY_2):
        for k in raw.split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)
    return keys


_key_index = 0


async def call_llm(
    messages: List[Dict],
    tools: Optional[List[Dict]] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.6,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    """Call LLM with automatic Groq key rotation and OpenAI fallback."""
    global _key_index

    is_openai = model in ("gpt-4o", "gpt-4o-mini", "gpt-4-turbo")

    if is_openai:
        return await _call_openai(messages, tools, model, temperature, max_tokens)

    groq_keys = _groq_keys()
    if not groq_keys:
        return await _call_openai(messages, tools, REASONING_MODEL, temperature, max_tokens)

    last_error = None
    for attempt in range(len(groq_keys) + 1):
        if attempt == len(groq_keys):
            logger.warning("[LLM] All Groq keys exhausted, falling back to OpenAI")
            return await _call_openai(messages, tools, REASONING_MODEL, temperature, max_tokens)

        key = groq_keys[_key_index % len(groq_keys)]
        _key_index += 1

        try:
            result = await _call_groq(key, messages, tools, model, temperature, max_tokens)
            return result
        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            if "rate_limit" in err_str or "429" in err_str:
                logger.warning(f"[LLM] Groq key rate limited, rotating...")
                await asyncio.sleep(0.5)
                continue
            raise

    raise last_error or RuntimeError("LLM call failed")


async def _call_groq(
    api_key: str,
    messages: List[Dict],
    tools: Optional[List[Dict]],
    model: str,
    temperature: float,
    max_tokens: int,
) -> Dict:
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )
        if resp.status_code == 429:
            raise RuntimeError(f"rate_limit_429: {resp.text[:200]}")
        resp.raise_for_status()
        return resp.json()


async def _call_openai(
    messages: List[Dict],
    tools: Optional[List[Dict]],
    model: str,
    temperature: float,
    max_tokens: int,
) -> Dict:
    if not OPENAI_API_KEY:
        raise RuntimeError("No OpenAI API key configured")

    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json=body,
        )
        resp.raise_for_status()
        return resp.json()
