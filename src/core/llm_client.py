"""LLM Client — ALL calls route through UnifiedLLMClient.

Uses the shared rg_llm library directly (mounted at /app/rg_llm).
Handles multi-provider fallback, BYOK keys, streaming, and tool calling.
"""
import asyncio
import inspect
import logging
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import httpx
from rg_llm import UnifiedLLMClient, LLMRequest, LLMStreamEvent, StreamEventType, ideal_provider_for

from src.core.config import LLM_SERVICE_URL

logger = logging.getLogger(__name__)

# No hardcoded model ids. Empty = "no preference" → the shared rg_llm client
# picks the best AVAILABLE provider for the task (provider-agnostic task-based
# routing, using each provider's own computed-cheapest default_model) and
# honors any explicit user preferred_provider/preferred_model. Hardcoding model
# snapshot ids here rots every time a provider retires one (see the repeated
# "default model retired" incidents), so we defer to the live catalog instead.
DEFAULT_MODEL = ""
FAST_MODEL = ""
REASONING_MODEL = ""

_client = UnifiedLLMClient()

_LIVE_MODEL_HINT_FALLBACK = "groq/llama-3.3-70b-versatile, openai/gpt-4o, anthropic/claude-sonnet-4-6"
_LIVE_MODEL_HINT_TTL = 120.0
_live_model_hint_cache: Dict[str, Any] = {"text": "", "ts": 0.0}


async def get_live_model_hint() -> str:
    """Short 'provider/model' example string built from LLM Service's real
    provider-liveness check (same source Anthropic key rotations etc. get
    verified against), so the architect's tool schemas never steer it toward
    a model that's since been retired — a static hardcoded example rots the
    same way the old per-service model whitelists did. Cached since this can
    be called on every architect turn; falls back to a static example on
    any failure so a live-service hiccup never blocks tool calling.
    """
    now = time.monotonic()
    if _live_model_hint_cache["text"] and now - _live_model_hint_cache["ts"] < _LIVE_MODEL_HINT_TTL:
        return _live_model_hint_cache["text"]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{LLM_SERVICE_URL}/llm/providers")
        if resp.status_code != 200:
            return _LIVE_MODEL_HINT_FALLBACK
        examples = [
            f"{p['id']}/{p['model']}"
            for p in resp.json().get("providers", [])
            if p.get("available") and p.get("model")
        ]
        text = ", ".join(examples) if examples else _LIVE_MODEL_HINT_FALLBACK
        _live_model_hint_cache["text"] = text
        _live_model_hint_cache["ts"] = now
        return text
    except Exception as e:
        logger.warning(f"[LiveModelHint] fetch failed, using static fallback: {e}")
        return _LIVE_MODEL_HINT_FALLBACK


def _parse_provider_model(model_str: str):
    """Parse 'provider/model' format into (provider, model) tuple."""
    if "/" in model_str:
        provider, model = model_str.split("/", 1)
        return provider, model
    return None, model_str


def resolve_model(preferred_provider: str, preferred_model: str, fallback: str) -> str:
    """Combine an explicit user provider+model choice into the 'provider/model'
    string this client's `model=` param expects, or fall back to the given
    constant (DEFAULT_MODEL/FAST_MODEL/REASONING_MODEL) when no choice was made."""
    if preferred_provider and preferred_model:
        return f"{preferred_provider}/{preferred_model}"
    return fallback


# Keyword hints for inferring which capability an agent's goal mostly needs —
# a small explicit heuristic (no cross-service capability router is reachable
# from this codebase; see rg_llm.capabilities for the canonical provider tags).
# Shared by builder.py and build_pipeline.py so both use one resolution path.
_CAPABILITY_KEYWORDS = {
    "coding": ["code", "coding", "program", "develop", "debug", "script", "software"],
    "image": ["image", "picture", "photo", "illustration", "graphic", "artwork"],
    "voice": ["voice", "audio", "podcast", "narration", "speech", "tts"],
    "long_context": ["large document", "long document", "entire codebase", "whole book"],
    "vision": ["screenshot", "look at this image", "analyze this photo"],
}


def infer_capability(goal: str) -> str:
    """Best-effort guess at which rg_llm capability tag fits this agent's goal."""
    low = (goal or "").lower()
    for capability, keywords in _CAPABILITY_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return capability
    return "general"


# A representative tool schema for probing — biases the probe toward a model
# that's reliable at tool-calling, since every built agent gets memory tools.
PROBE_TOOLS = [{
    "type": "function",
    "function": {
        "name": "memory_write",
        "description": "Store a memory for later recall.",
        "parameters": {"type": "object", "properties": {"content": {"type": "string"}}},
    },
}]


async def probe_working_provider(
    capability: str = "general",
    tools: Optional[List[Dict]] = None,
    user_api_keys: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Find which provider (system key or the user's own BYOK key) actually
    works for a given capability, BEFORE committing an agent to a model —
    replaces the old pattern of picking a model first and testing it after
    the fact.

    Sends one minimal real request biased toward the ideal provider for
    `capability`. Because rg_llm's fallback chain now cascades through every
    provider/key (system then BYOK, across the whole fallback order) whenever
    the preferred one fails, this single call is enough to discover both
    "does anything work at all" and "did we get the ideal provider, or a
    working substitute."

    Returns:
        provider: "" if nothing works at all, else the provider id that
            actually answered.
        is_ideal: whether that provider is the best fit for `capability`
            (False means a substitute was used and the caller should mark
            it as temporary).
        ideal_provider: the provider id that would have been ideal.
        model / was_fallback / fallback_chain: as returned by rg_llm, for
            diagnostics and user-facing messaging.
    """
    ideal = ideal_provider_for(capability)
    request = LLMRequest(
        messages=[{"role": "user", "content": "Reply with the single word: OK"}],
        provider=ideal,
        model=None,
        max_tokens=5,
        tools=tools,
    )
    response = await _client.complete(request, user_keys=user_api_keys)
    provider = response.provider or ""
    if provider == "none":
        provider = ""
    return {
        "provider": provider,
        "model": response.model or "",
        "was_fallback": response.was_fallback,
        "fallback_chain": response.fallback_chain or [],
        "ideal_provider": ideal,
        "is_ideal": bool(provider) and provider == ideal,
    }


async def call_llm(
    messages: List[Dict],
    tools: Optional[List[Dict]] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.6,
    max_tokens: int = 16000,
    user_api_keys: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Single entry point for all LLM calls in agent_architect.

    Returns OpenAI-compatible dict with choices[0].message for backward compat.
    """
    provider, model_name = _parse_provider_model(model)

    print(f"[LLM] Calling model={model} provider={provider or 'auto'} tools={len(tools) if tools else 0} msgs={len(messages)}", flush=True)

    request = LLMRequest(
        messages=messages,
        provider=provider,
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
    )

    try:
        response = await _client.complete(request, user_keys=user_api_keys)
    except Exception as e:
        logger.error(f"[LLM] call failed: {e}")
        raise

    # DEFAULT_MODEL/FAST_MODEL/REASONING_MODEL are tokenrouter-prefixed, which
    # forces strict mode in rg_llm (no cross-provider fallback). If TokenRouter
    # is down/out of credit, retry once via auto-fallback so BYOK keys get tried.
    if response.provider == "none" and user_api_keys:
        logger.warning(f"[LLM] {provider or 'default'} unavailable, retrying via auto-fallback with BYOK keys")
        fallback_request = LLMRequest(
            messages=messages, provider=None, model="",
            temperature=temperature, max_tokens=max_tokens, tools=tools,
        )
        response = await _client.complete(fallback_request, user_keys=user_api_keys)

    # Build OpenAI-compatible response dict for backward compat
    message: Dict[str, Any] = {"role": "assistant", "content": response.content or ""}
    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id": tc.id or f"call_{i}",
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for i, tc in enumerate(response.tool_calls)
        ]

    result = {
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": response.usage.get("prompt_tokens", 0) if response.usage else 0,
            "completion_tokens": response.usage.get("completion_tokens", 0) if response.usage else 0,
            "total_tokens": response.usage.get("total_tokens", 0) if response.usage else 0,
        },
        "provider": response.provider or "",
        "model": response.model or model_name,
    }

    tc_count = len(response.tool_calls) if response.tool_calls else 0
    content_len = len(response.content or "")
    print(f"[LLM] Response via {response.provider}/{response.model}: tool_calls={tc_count}, content_len={content_len}", flush=True)
    return result


async def call_llm_stream(
    messages: List[Dict],
    tools: Optional[List[Dict]] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.6,
    max_tokens: int = 16000,
    user_api_keys: Optional[Dict[str, str]] = None,
    on_chunk: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """Streaming LLM call — emits tokens via on_chunk callback as they arrive.

    Returns the same OpenAI-compatible dict as call_llm() for backward compat,
    but calls on_chunk(token) for each token so the orchestrator can stream live.
    """
    provider, model_name = _parse_provider_model(model)

    print(f"[LLM-stream] Calling model={model} provider={provider or 'auto'} tools={len(tools) if tools else 0} msgs={len(messages)}", flush=True)

    request = LLMRequest(
        messages=messages,
        provider=provider,
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
    )

    accumulated_content = ""
    accumulated_tool_calls: List[Any] = []
    actual_provider = ""
    actual_model = model_name
    usage: Dict[str, int] = {}

    async def _consume(req: LLMRequest) -> None:
        nonlocal accumulated_content, accumulated_tool_calls, actual_provider, actual_model, usage
        async for event in _client.stream(req, user_keys=user_api_keys):
            if event.event == StreamEventType.CHUNK:
                accumulated_content += event.content
                if on_chunk and event.content:
                    if inspect.iscoroutinefunction(on_chunk):
                        await on_chunk(event.content)
                    else:
                        on_chunk(event.content)
            elif event.event == StreamEventType.TOOL_CALLS:
                accumulated_tool_calls = event.tool_calls
            elif event.event == StreamEventType.PROVIDER:
                actual_provider = event.provider
                actual_model = event.model or model_name
            elif event.event == StreamEventType.DONE:
                actual_provider = event.provider or actual_provider
                actual_model = event.model or actual_model
                usage = event.usage or {}
            elif event.event == StreamEventType.ERROR:
                raise Exception(event.error or "Streaming failed")

    try:
        await _consume(request)
    except Exception as e:
        # DEFAULT_MODEL/FAST_MODEL/REASONING_MODEL are tokenrouter-prefixed,
        # which forces strict mode in rg_llm (no cross-provider fallback). If
        # TokenRouter is down/out of credit, retry once via auto-fallback so
        # BYOK keys get tried — but only if nothing has streamed to the user yet.
        if user_api_keys and not accumulated_content and not accumulated_tool_calls:
            logger.warning(f"[LLM-stream] {provider or 'default'} unavailable ({e}), retrying via auto-fallback with BYOK keys")
            fallback_request = LLMRequest(
                messages=messages, provider=None, model="",
                temperature=temperature, max_tokens=max_tokens, tools=tools,
            )
            try:
                await _consume(fallback_request)
            except Exception as e2:
                logger.error(f"[LLM-stream] fallback also failed: {e2}")
                raise
        else:
            logger.error(f"[LLM-stream] failed: {e}")
            raise

    # Build OpenAI-compatible response dict
    message: Dict[str, Any] = {"role": "assistant", "content": accumulated_content}
    if accumulated_tool_calls:
        message["tool_calls"] = [
            {
                "id": tc.id or f"call_{i}",
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for i, tc in enumerate(accumulated_tool_calls)
        ]

    result = {
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "provider": actual_provider,
        "model": actual_model,
    }

    tc_count = len(accumulated_tool_calls)
    print(f"[LLM-stream] Response via {actual_provider}/{actual_model}: tool_calls={tc_count}, content_len={len(accumulated_content)}", flush=True)
    return result
