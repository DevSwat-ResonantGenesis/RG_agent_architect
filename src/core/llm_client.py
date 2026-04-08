"""LLM Client — Unified service for chat, direct provider for tool calls"""
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.core.config import LLM_SERVICE_URL, GROQ_API_KEY, OPENAI_API_KEY

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "groq/llama-3.3-70b-versatile"
FAST_MODEL = "groq/llama-3.1-8b-instant"
REASONING_MODEL = "openai/gpt-4o"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


async def call_llm(
    messages: List[Dict],
    tools: Optional[List[Dict]] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.6,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    if tools:
        return await _call_direct(messages, tools, model, temperature, max_tokens)
    return await _call_unified(messages, model, temperature, max_tokens)


async def _call_unified(messages, model, temperature, max_tokens) -> Dict[str, Any]:
    """Plain chat through unified llm_service."""
    url = f"{LLM_SERVICE_URL}/llm/chat/completions"
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"[LLM] unified call failed: {e}")
        raise


async def _call_direct(messages, tools, model, temperature, max_tokens) -> Dict[str, Any]:
    """Tool-calling: call provider directly (unified LLM strips tools)."""
    is_openai = model.startswith("openai/")
    if is_openai:
        url = OPENAI_URL
        api_key = OPENAI_API_KEY
        actual_model = model.replace("openai/", "")
    else:
        url = GROQ_URL
        api_key = GROQ_API_KEY
        actual_model = model.replace("groq/", "")

    if not api_key:
        raise RuntimeError(f"No API key for {'OpenAI' if is_openai else 'Groq'}")

    body: Dict[str, Any] = {
        "model": actual_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "tools": tools,
        "tool_choice": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                url, json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"[LLM] direct call failed: {e}")
        raise
