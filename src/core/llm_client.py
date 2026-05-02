"""LLM Client — ALL calls route through UnifiedLLMClient.

Uses the shared rg_llm library directly (mounted at /app/rg_llm).
Handles multi-provider fallback, BYOK keys, streaming, and tool calling.
"""
import logging
from typing import Any, Dict, List, Optional

from rg_llm import UnifiedLLMClient, LLMRequest

logger = logging.getLogger(__name__)

# Model defaults — NO provider prefix so UnifiedLLMClient uses full fallback chain.
# The client will try tokenrouter → openai → anthropic → groq → google etc.
DEFAULT_MODEL = "llama-3.3-70b-versatile"
FAST_MODEL = "llama-3.1-8b-instant"
REASONING_MODEL = "gpt-4o"

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
        provider=provider,  # None = full fallback chain, set = strict single provider
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
