"""LLM Client — ALL calls route through the unified LLM service.

No direct Groq/OpenAI calls. No duplicate API keys.
The unified service handles routing, BYOK, billing, and fallback.
For tool-calling we set provider=openai since the multi_router Groq
path strips tools. OpenAI provider in the unified service handles
tools natively.
"""
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.core.config import LLM_SERVICE_URL

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "groq/llama-3.3-70b-versatile"
FAST_MODEL = "groq/llama-3.1-8b-instant"
REASONING_MODEL = "openai/gpt-4o"

_URL = f"{LLM_SERVICE_URL}/llm/chat/completions"


async def call_llm(
    messages: List[Dict],
    tools: Optional[List[Dict]] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.6,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    """Single entry point — everything goes through the unified LLM service."""
    body: Dict[str, Any] = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if tools:
        # Tool-calling must go through OpenAI provider (multi_router strips tools)
        body["tools"] = tools
        body["tool_choice"] = "auto"
        body["provider"] = "openai"
        body["model"] = "gpt-4o"
    else:
        body["model"] = model

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(_URL, json=body)
            if resp.status_code != 200:
                logger.error(f"[LLM] {resp.status_code}: {resp.text[:500]}")
            resp.raise_for_status()
            data = resp.json()
            return _normalize_response(data)
    except Exception as e:
        logger.error(f"[LLM] call failed: {e}")
        raise


def _normalize_response(data: Dict) -> Dict:
    """Ensure tool_calls are inside message (raw OpenAI format).

    The unified service may return tool_calls at the choice level
    (ChatCompletionChoice.tool_calls) instead of inside message.
    The orchestrator expects them in message, so we normalize here.
    """
    for choice in data.get("choices", []):
        tc = choice.pop("tool_calls", None)
        if tc and "message" in choice:
            if not choice["message"].get("tool_calls"):
                choice["message"]["tool_calls"] = tc
    return data
