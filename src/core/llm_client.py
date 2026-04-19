"""LLM Client — ALL calls route through the unified LLM service.

No direct Groq/OpenAI calls. No duplicate API keys.
The unified service handles routing, BYOK, billing, and fallback.
Tool-calling goes through the multi_router which passes tools to
Groq/OpenAI natively.
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
    max_tokens: int = 16000,
) -> Dict[str, Any]:
    """Single entry point — everything goes through the unified LLM service."""
    body: Dict[str, Any] = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    body["model"] = model
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    print(f"[LLM] Calling model={model} tools={len(tools) if tools else 0} msgs={len(messages)}", flush=True)

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(_URL, json=body)
            if resp.status_code != 200:
                print(f"[LLM] ERROR {resp.status_code}: {resp.text[:300]}", flush=True)
                logger.error(f"[LLM] {resp.status_code}: {resp.text[:500]}")
            resp.raise_for_status()
            data = resp.json()
            normalized = _normalize_response(data)
            tc = normalized.get("choices", [{}])[0].get("message", {}).get("tool_calls")
            print(f"[LLM] Response: tool_calls={len(tc) if tc else 0}, content_len={len(normalized.get('choices', [{}])[0].get('message', {}).get('content', '') or '')}", flush=True)
            return normalized
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
