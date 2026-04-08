"""
RG Agent Architect — Orchestrator

Twin's ReAct loop: think → tool_call → observe → repeat.
- Session init: parallel context fetch (twin.md lines 365-367)
- Mode classification: brainstorm / control / review (twin.md lines 369-373)
- Tool execution with all 36 tools
- SSE streaming for real-time frontend updates
- Terminal actions: respond_to_user, present_options
"""
import json
import logging
from typing import AsyncGenerator

from ..config import settings
from .prompts import build_system_prompt
from .context import fetch_workspace_context, build_context_summary
from .llm_client import call_llm
from .tools import AGENT_TOOLS
from .tool_executor import execute_tool

logger = logging.getLogger(__name__)


async def orchestrate(
    message: str,
    user_id: str,
    context: dict,
    headers: dict,
    user_api_keys: dict | None = None,
) -> dict:
    """Main orchestration entry point.

    1. Fetch workspace context (parallel: agents + tools + memory)
    2. Build system prompt with context
    3. Run ReAct loop: LLM → tool calls → results → repeat
    4. Return structured response

    Returns: {response, options, metadata}
    """
    # Step 1: Session init — parallel context fetch
    workspace_ctx = await fetch_workspace_context(user_id, headers)
    agents = workspace_ctx.get("agents", [])
    context_summary = build_context_summary(workspace_ctx)

    # Step 2: Build messages
    system_prompt = build_system_prompt()
    system_msg = f"{system_prompt}\n\n<workspace_context>\n{context_summary}\n</workspace_context>"

    # Include conversation history if provided
    history = context.get("history", [])[-settings.ORCHESTRATOR_HISTORY_DEPTH:]

    messages = [{"role": "system", "content": system_msg}]
    for h in history:
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:settings.ORCHESTRATOR_MSG_TRUNCATE]})
    messages.append({"role": "user", "content": message})

    # Step 3: ReAct loop
    final_response = ""
    options = []
    metadata: dict = {"tools_called": [], "iterations": 0}

    for iteration in range(settings.ORCHESTRATOR_MAX_ITERATIONS):
        metadata["iterations"] = iteration + 1

        try:
            llm_resp = await call_llm(
                messages=messages,
                tools=AGENT_TOOLS,
                provider=settings.DEFAULT_PROVIDER,
                model=settings.DEFAULT_MODEL,
                user_api_keys=user_api_keys or {},
            )
        except Exception as e:
            logger.error(f"[ORCH] LLM call failed: {e}")
            return {"response": f"I had trouble processing that. Error: {e}", "options": [], "metadata": metadata}

        choice = llm_resp.get("choices", [{}])[0]
        msg = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")
        tool_calls = msg.get("tool_calls")
        content = msg.get("content") or ""

        # Append assistant message to history
        assistant_msg: dict = {"role": "assistant"}
        if content:
            assistant_msg["content"] = content
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        # No tool calls → LLM finished
        if not tool_calls:
            final_response = content
            break

        # Execute tool calls
        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            metadata["tools_called"].append(tool_name)

            # Terminal: respond_to_user
            if tool_name == "respond_to_user":
                final_response = args.get("message", content)
                options = args.get("options", [])
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": "Response delivered."})
                return {"response": final_response, "options": options, "metadata": metadata}

            # Semi-terminal: present_options
            if tool_name == "present_options":
                result = json.dumps({
                    "type": "present_options",
                    "question": args.get("question", ""),
                    "options": args.get("options", []),
                    "question_type": args.get("question_type", "PickOne"),
                    "scope_warning": args.get("scope_warning"),
                })
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                return {
                    "response": args.get("question", ""),
                    "options": args.get("options", []),
                    "question_type": args.get("question_type", "PickOne"),
                    "scope_warning": args.get("scope_warning"),
                    "metadata": metadata,
                }

            # Execute tool
            result = await execute_tool(tool_name, args, headers, agents)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result[:settings.ORCHESTRATOR_MSG_TRUNCATE]})

    if not final_response:
        final_response = "I've completed the requested actions."

    return {"response": final_response, "options": options, "metadata": metadata}


async def orchestrate_stream(
    message: str,
    user_id: str,
    context: dict,
    headers: dict,
    user_api_keys: dict | None = None,
) -> AsyncGenerator[str, None]:
    """SSE streaming version of orchestrate.

    Yields events:
    - status: context gathering progress
    - thinking: ReAct iteration
    - tool_call: which tool is being called
    - tool_result: tool execution result
    - done: final structured response
    """
    def sse(event_type: str, data: dict) -> str:
        return f"data: {json.dumps({'type': event_type, **data})}\n\n"

    yield sse("status", {"message": "Gathering workspace context..."})

    # Step 1: Context
    workspace_ctx = await fetch_workspace_context(user_id, headers)
    agents = workspace_ctx.get("agents", [])
    context_summary = build_context_summary(workspace_ctx)

    yield sse("status", {"message": f"Context loaded: {len(agents)} agents"})

    # Step 2: Messages
    system_prompt = build_system_prompt()
    system_msg = f"{system_prompt}\n\n<workspace_context>\n{context_summary}\n</workspace_context>"

    history = context.get("history", [])[-settings.ORCHESTRATOR_HISTORY_DEPTH:]
    messages = [{"role": "system", "content": system_msg}]
    for h in history:
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:settings.ORCHESTRATOR_MSG_TRUNCATE]})
    messages.append({"role": "user", "content": message})

    metadata: dict = {"tools_called": [], "iterations": 0}

    # Step 3: ReAct loop
    for iteration in range(settings.ORCHESTRATOR_MAX_ITERATIONS):
        metadata["iterations"] = iteration + 1
        yield sse("thinking", {"iteration": iteration + 1})

        try:
            llm_resp = await call_llm(
                messages=messages,
                tools=AGENT_TOOLS,
                provider=settings.DEFAULT_PROVIDER,
                model=settings.DEFAULT_MODEL,
                user_api_keys=user_api_keys or {},
            )
        except Exception as e:
            yield sse("error", {"message": str(e)})
            yield sse("done", {"response": f"Error: {e}", "options": [], "metadata": metadata})
            return

        choice = llm_resp.get("choices", [{}])[0]
        msg = choice.get("message", {})
        tool_calls = msg.get("tool_calls")
        content = msg.get("content") or ""

        assistant_msg: dict = {"role": "assistant"}
        if content:
            assistant_msg["content"] = content
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        if not tool_calls:
            yield sse("done", {"response": content, "options": [], "metadata": metadata})
            return

        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            metadata["tools_called"].append(tool_name)
            yield sse("tool_call", {"tool": tool_name, "args": {k: str(v)[:100] for k, v in args.items()}})

            if tool_name == "respond_to_user":
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": "Response delivered."})
                yield sse("done", {"response": args.get("message", content), "options": args.get("options", []), "metadata": metadata})
                return

            if tool_name == "present_options":
                result_data = {"type": "present_options", "question": args.get("question", ""), "options": args.get("options", []), "question_type": args.get("question_type", "PickOne"), "scope_warning": args.get("scope_warning")}
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result_data)})
                yield sse("done", {"response": args.get("question", ""), "options": args.get("options", []), "question_type": args.get("question_type", "PickOne"), "scope_warning": args.get("scope_warning"), "metadata": metadata})
                return

            result = await execute_tool(tool_name, args, headers, agents)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result[:settings.ORCHESTRATOR_MSG_TRUNCATE]})
            yield sse("tool_result", {"tool": tool_name, "result": result[:300]})

    yield sse("done", {"response": "Completed requested actions.", "options": [], "metadata": metadata})
