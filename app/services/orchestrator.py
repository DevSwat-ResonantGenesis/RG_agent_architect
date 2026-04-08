"""
RG Agent Architect — Main Orchestrator (ReAct Agent Loop)

Instead of regex-based intent routing, uses LLM function-calling to decide
what to do. The LLM sees the user's message, available tools, and workspace
context, then autonomously calls the right tools to fulfill the request.

Flow:
1. Fetch workspace context (agents, tools, memory) — 3 parallel calls
2. Build system prompt + conversation history
3. ReAct loop: LLM → tool call → execute → observe → LLM → ...
4. When LLM responds with text (no tool calls) → return to user
"""
import json
import logging
import re

from .prompts import build_system_prompt
from .llm_client import llm_call_with_tools, llm_json
from .context import fetch_workspace_context, store_memory
from .tools import AGENT_TOOLS
from .tool_executor import execute_tool

logger = logging.getLogger(__name__)

PANEL_URL = "/agents?embed=1"
MAX_TOOL_ITERATIONS = 10  # Safety limit on ReAct loop


# ═══════════════════════════════════════════════════════════════
# MAIN ORCHESTRATE ENTRY POINT — ReAct Agent Loop
# ═══════════════════════════════════════════════════════════════

async def orchestrate(
    message: str,
    user_id: str,
    context: dict,
    headers: dict[str, str],
    user_api_keys: dict | None = None,
) -> dict:
    """ReAct agent loop orchestration.

    The LLM decides what to do — no regex routing. It can:
    - Call tools (list_agents, delete_agent, create_agent, etc.)
    - Observe tool results
    - Call more tools based on what it learned
    - Respond to the user when it has enough information

    This replaces the old classify_intent → route_to_handler pattern.
    """
    logger.info(f"🏗️ [ORCHESTRATE] Message: {message[:120]!r}")
    print(f"[ORCHESTRATE] Starting ReAct loop for: {message[:100]!r}", flush=True)

    # Step 1: Context Protocol — gather workspace state (3 parallel calls)
    workspace = await fetch_workspace_context(user_id, headers)
    agents = workspace.get("agents", [])
    agent_count = len(agents)

    logger.info(f"🏗️ [ORCHESTRATE] Context: {agent_count} agents, tools={workspace.get('tools_summary')}")

    # Step 2: Build system prompt with workspace context injected
    system_prompt = build_system_prompt()
    context_block = _build_context_block(workspace, agents)
    full_system = f"{system_prompt}\n\n{context_block}"

    # Step 3: Build conversation messages
    # Include recent conversation history for continuity
    messages = [{"role": "system", "content": full_system}]

    prev_msgs = context.get("messages") or context.get("previousMessages") or context.get("previous_messages") or []
    for m in prev_msgs[-6:]:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:1000]})

    messages.append({"role": "user", "content": message})

    # Step 4: ReAct loop — LLM thinks and calls tools until it has a final answer
    for iteration in range(MAX_TOOL_ITERATIONS):
        print(f"[ORCHESTRATE] ReAct iteration {iteration + 1}/{MAX_TOOL_ITERATIONS}", flush=True)

        response = await llm_call_with_tools(
            messages, AGENT_TOOLS,
            user_api_keys=user_api_keys,
            temperature=0.2,
            max_tokens=2000,
        )

        if not response:
            logger.warning("[ORCHESTRATE] LLM returned None — falling back")
            return _fallback_response(message, agents)

        tool_calls = response.get("tool_calls", [])
        content = response.get("content") or ""

        # If LLM responds with text only (no tool calls) → it's the final answer
        if not tool_calls:
            print(f"[ORCHESTRATE] LLM final response (no tools): {content[:200]!r}", flush=True)
            return _format_text_response(content, agents)

        # Add assistant message with tool calls to conversation
        messages.append(response)

        # Execute each tool call
        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            try:
                arguments = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                arguments = {}

            print(f"[ORCHESTRATE] Tool call: {tool_name}({json.dumps(arguments)[:100]})", flush=True)

            # Special case: respond_to_user is terminal
            if tool_name == "respond_to_user":
                return _format_respond_to_user(arguments, agents)

            # Execute the tool
            result = await execute_tool(tool_name, arguments, headers, agents)
            print(f"[ORCHESTRATE] Tool result: {result[:200]!r}", flush=True)

            # Feed result back to LLM
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result,
            })

    # Safety: max iterations reached
    logger.warning(f"[ORCHESTRATE] Max iterations ({MAX_TOOL_ITERATIONS}) reached")
    return _format_text_response(
        "I've been working on your request but hit the iteration limit. Here's what I found so far.",
        agents,
    )


# ═══════════════════════════════════════════════════════════════
# ReAct HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def _build_context_block(workspace: dict, agents: list[dict]) -> str:
    """Build a context block to inject into the system prompt so the LLM
    knows about the user's current workspace state."""
    parts = ["<current_workspace>"]

    if agents:
        parts.append(f"User has {len(agents)} agent(s):")
        for a in agents[:15]:
            status = "active" if a.get("is_active") else "inactive"
            tools = ", ".join(a.get("tools", [])[:5])
            parts.append(f"  - {a.get('name', '?')} ({a.get('model', '?')}) [{status}] tools: {tools}")
    else:
        parts.append("User has no agents yet — fresh workspace.")

    tools_summary = workspace.get("tools_summary", "160+ tools available")
    parts.append(f"\nPlatform: {tools_summary}")

    memory = workspace.get("memory_facts", "")
    if memory:
        parts.append(f"\nUser context from memory: {memory[:300]}")

    parts.append("</current_workspace>")
    return "\n".join(parts)


def _format_text_response(content: str, agents: list[dict]) -> dict:
    """Format a plain text LLM response into the structured response format."""
    # Generate sensible default follow-up options
    options = []
    if agents:
        options.append({
            "label": "Show my agents",
            "value": "Agent Architect: show my agents",
            "description": "Workspace overview",
            "icon": "📋",
        })
        options.append({
            "label": "Build new agent",
            "value": "Agent Architect: build a new agent",
            "description": "Create something new",
            "icon": "🏗️",
        })
    else:
        options.append({
            "label": "Build an agent",
            "value": "Agent Architect: help me build my first agent",
            "description": "Get started",
            "icon": "🏗️",
        })
        options.append({
            "label": "Explore ideas",
            "value": "Agent Architect: what kinds of agents can you build?",
            "description": "See what's possible",
            "icon": "💡",
        })

    return {
        "success": True,
        "action": "open_agents_panel",
        "panel_url": PANEL_URL,
        "intent": "RESPOND",
        "operation": "react_response",
        "summary": content,
        "present_options": {
            "_type": "present_options",
            "title": "What's next?",
            "options": options[:4],
            "allow_custom": True,
        },
    }


def _format_respond_to_user(arguments: dict, agents: list[dict]) -> dict:
    """Format the respond_to_user tool call into a structured response."""
    message = arguments.get("message", "Done.")
    options = arguments.get("options", [])

    # Ensure options have all required fields
    formatted_options = []
    for opt in options[:4]:
        formatted_options.append({
            "label": opt.get("label", "Continue"),
            "value": opt.get("value", "Agent Architect: continue"),
            "description": opt.get("description", ""),
            "icon": opt.get("icon", "▶️"),
        })

    # Add default options if none provided
    if not formatted_options:
        if agents:
            formatted_options.append({
                "label": "Show my agents",
                "value": "Agent Architect: show my agents",
                "description": "See workspace",
                "icon": "📋",
            })
        formatted_options.append({
            "label": "Build an agent",
            "value": "Agent Architect: build a new agent",
            "description": "Create something new",
            "icon": "🏗️",
        })

    return {
        "success": True,
        "action": "open_agents_panel",
        "panel_url": PANEL_URL,
        "intent": "RESPOND",
        "operation": "react_response",
        "summary": message,
        "present_options": {
            "_type": "present_options",
            "title": "What's next?",
            "options": formatted_options,
            "allow_custom": True,
        },
    }


def _fallback_response(message: str, agents: list[dict]) -> dict:
    """Fallback when the LLM fails entirely."""
    return {
        "success": False,
        "action": "open_agents_panel",
        "panel_url": PANEL_URL,
        "intent": "BUILD",
        "operation": "fallback",
        "error": "LLM call failed",
        "summary": "I'm having trouble connecting right now. Please try again in a moment.",
        "present_options": {
            "_type": "present_options",
            "title": "Try again",
            "options": [
                {
                    "label": "Retry",
                    "value": f"Agent Architect: {message[:80]}",
                    "description": "Try again",
                    "icon": "🔄",
                },
            ],
            "allow_custom": True,
        },
    }
