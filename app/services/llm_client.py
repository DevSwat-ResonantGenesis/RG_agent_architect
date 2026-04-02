"""
RG Agent Architect — LLM Client
Groq (primary) → OpenAI (fallback). Supports JSON mode.
"""
import json
import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


async def llm_call(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    json_mode: bool = False,
    user_api_keys: dict | None = None,
    timeout: float = 25.0,
) -> str | None:
    """Call LLM with Groq-first, OpenAI fallback. Returns raw content string."""
    model = model or settings.DEFAULT_MODEL
    body: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    # Collect Groq keys: user-provided first, then env
    groq_keys = []
    if user_api_keys and user_api_keys.get("groq"):
        groq_keys.append(user_api_keys["groq"])
    groq_keys.extend(k for k in settings.groq_keys() if k not in groq_keys)

    # Try Groq
    for key in groq_keys:
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
                resp = await c.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=body,
                )
                if resp.status_code in (401, 429):
                    continue
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"[LLM] Groq call failed: {e}")
            continue

    # Fallback: OpenAI
    openai_key = settings.OPENAI_API_KEY
    if user_api_keys and user_api_keys.get("openai"):
        openai_key = user_api_keys["openai"]
    if openai_key:
        try:
            oai_body = {**body, "model": settings.REASONING_MODEL}
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
                resp = await c.post(
                    OPENAI_URL,
                    headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                    json=oai_body,
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"[LLM] OpenAI fallback failed: {e}")

    return None


async def llm_json(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    user_api_keys: dict | None = None,
    timeout: float = 25.0,
) -> dict | None:
    """Call LLM and parse JSON response. Returns dict or None."""
    raw = await llm_call(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=True,
        user_api_keys=user_api_keys,
        timeout=timeout,
    )
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown fences
        import re
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        logger.warning(f"[LLM] Failed to parse JSON: {raw[:200]}")
        return None


async def llm_fast(
    prompt: str,
    *,
    user_api_keys: dict | None = None,
    max_tokens: int = 30,
) -> str:
    """Ultra-fast single-token-ish call using speed model. Returns stripped text."""
    result = await llm_call(
        [{"role": "user", "content": prompt}],
        model=settings.FAST_MODEL,
        temperature=0.0,
        max_tokens=max_tokens,
        user_api_keys=user_api_keys,
        timeout=8.0,
    )
    return (result or "").strip()
