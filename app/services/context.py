"""
RG Agent Architect — Workspace Context

Twin session_start (twin.md lines 365-367):
"At the start of every session, call workspace_snapshot, get_user_memory,
and list_workspace_tools in parallel."

This module fetches all three in parallel and returns a unified context dict.
"""
import asyncio
import json
import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

AGENT_ENGINE_URL = settings.AGENT_ENGINE_URL
MEMORY_SERVICE_URL = settings.MEMORY_SERVICE_URL


async def fetch_workspace_context(user_id: str, headers: dict) -> dict:
    """Fetch workspace context in parallel: agents + tools + memory.

    Returns:
        {
            "agents": [...],
            "tools_summary": "...",
            "tools_by_category": {...},
            "memory_facts": "...",
        }
    """
    agents_task = _fetch_agents(headers)
    tools_task = _fetch_tools(headers)
    memory_task = _fetch_memory(user_id, headers)

    agents, tools_info, memory = await asyncio.gather(
        agents_task, tools_task, memory_task,
        return_exceptions=True,
    )

    # Handle exceptions gracefully
    if isinstance(agents, Exception):
        logger.warning(f"[CONTEXT] Agents fetch failed: {agents}")
        agents = []
    if isinstance(tools_info, Exception):
        logger.warning(f"[CONTEXT] Tools fetch failed: {tools_info}")
        tools_info = {"summary": "160+ tools available", "by_category": {}}
    if isinstance(memory, Exception):
        logger.warning(f"[CONTEXT] Memory fetch failed: {memory}")
        memory = ""

    return {
        "agents": agents,
        "tools_summary": tools_info.get("summary", "160+ tools available"),
        "tools_by_category": tools_info.get("by_category", {}),
        "memory_facts": memory,
    }


async def _fetch_agents(headers: dict) -> list[dict]:
    """Fetch all agents in the user's workspace."""
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
            resp = await c.get(f"{AGENT_ENGINE_URL}/agents/", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else data.get("agents", [])
    except Exception as e:
        logger.warning(f"[CONTEXT] Agent list failed: {e}")
    return []


async def _fetch_tools(headers: dict) -> dict:
    """Fetch available platform tools (list_workspace_tools)."""
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
            resp = await c.get(f"{AGENT_ENGINE_URL}/agents/tools/list", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                tools = data if isinstance(data, list) else data.get("tools", [])
                by_cat: dict[str, list[str]] = {}
                for t in tools:
                    cat = t.get("category", "other") if isinstance(t, dict) else "other"
                    name = t.get("name", str(t)) if isinstance(t, dict) else str(t)
                    by_cat.setdefault(cat, []).append(name)
                return {"summary": f"{len(tools)} tools available", "by_category": by_cat}
    except Exception as e:
        logger.warning(f"[CONTEXT] Tools fetch failed: {e}")
    return {"summary": "160+ tools available", "by_category": {}}


async def _fetch_memory(user_id: str, headers: dict) -> str:
    """Fetch user memory facts (get_user_memory)."""
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as c:
            resp = await c.post(
                f"{MEMORY_SERVICE_URL}/memory/search",
                json={"query": "user preferences role company", "user_id": user_id, "limit": 10},
                headers=headers,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    facts = [m.get("content", "")[:200] for m in results[:10]]
                    return " | ".join(f for f in facts if f)
    except Exception as e:
        logger.warning(f"[CONTEXT] Memory fetch failed: {e}")
    return ""


def build_context_summary(ctx: dict) -> str:
    """Build a compact context string for the LLM system message."""
    agents = ctx.get("agents", [])
    lines = []

    if agents:
        lines.append(f"Workspace: {len(agents)} agents")
        for a in agents[:10]:
            status = "active" if a.get("is_active") else "inactive"
            name = a.get("name", "?")
            model = a.get("model", "?")
            tools_count = len(a.get("tools", []))
            lines.append(f"  - {name} ({status}, {model}, {tools_count} tools)")
    else:
        lines.append("Workspace: empty (no agents yet)")

    tools_summary = ctx.get("tools_summary", "")
    if tools_summary:
        lines.append(f"Platform: {tools_summary}")

    memory = ctx.get("memory_facts", "")
    if memory:
        lines.append(f"User context: {memory[:300]}")

    return "\n".join(lines)
