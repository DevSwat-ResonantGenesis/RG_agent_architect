"""LLM Client — Routes through unified llm_service on Docker network"""
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.core.config import LLM_SERVICE_URL

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "groq/llama-3.3-70b-versatile"
FAST_MODEL = "groq/llama-3.1-8b-instant"
REASONING_MODEL = "openai/gpt-4o"


async def call_llm(
    messages: List[Dict],
    tools: Optional[List[Dict]] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.6,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    """Call LLM through the unified llm_service (handles routing, keys, rate limits)."""
    url = f"{LLM_SERVICE_URL}/llm/chat/completions"
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"[LLM] call failed: {e}")
        raise
