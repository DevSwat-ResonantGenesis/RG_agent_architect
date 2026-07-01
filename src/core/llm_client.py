"""LLM Client — ALL calls route through UnifiedLLMClient.

Uses the shared rg_llm library directly (mounted at /app/rg_llm).
Handles multi-provider fallback, BYOK keys, streaming, and tool calling.
"""
import asyncio
import inspect
import logging
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from rg_llm import UnifiedLLMClient, LLMRequest, LLMStreamEvent, StreamEventType

logger = logging.getLogger(__name__)

# Model defaults — use known-working TokenRouter models with provider prefix.
# These models are verified working in the TokenRouter catalog.
DEFAULT_MODEL = "tokenrouter/google/gemini-3-flash-preview"
FAST_MODEL = "tokenrouter/qwen/qwen3.5-flash"
REASONING_MODEL = "tokenrouter/anthropic/claude-opus-4.7"

_client = UnifiedLLMClient()


def _parse_provider_model(model_str: str):
    """Parse 'provider/model' format into (provider, model) tuple."""
    if "/" in model_str:
        provider, model = model_str.split("/", 1)
        return provider, model
    return None, model_str


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
