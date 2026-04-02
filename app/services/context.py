"""
RG Agent Architect — Context Protocol
Fetches workspace state, tools, and user memory in parallel before any decision.
"""
import asyncio
import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


async def fetch_workspace_context(
    user_id: str,
    headers: dict[str, str],
) -> dict:
    """Fetch agents, tools summary, and user memory — 3 parallel calls.

    Returns dict with keys: agents, tools_summary, memory_facts
    """
    ctx: dict = {"agents": [], "tools_summary": "160+ tools available", "memory_facts": ""}

    async def _fetch_agents():
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
                r = await c.get(f"{settings.AGENT_ENGINE_URL}/agents/", headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    agents = data if isinstance(data, list) else data.get("agents", [])
                    ctx["agents"] = [
                        {
                            "name": a.get("name", "?"),
                            "id": a.get("id"),
                            "model": a.get("model", "?"),
                            "provider": a.get("provider", "?"),
                            "tools": a.get("tools", []),
                            "is_active": a.get("is_active", False),
                            "description": a.get("description", ""),
                            "mode": a.get("mode", "governed"),
                        }
                        for a in agents[:20]
                    ]
        except Exception as e:
            logger.debug(f"[CTX] agents fetch: {e}")

    async def _fetch_tools():
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as c:
                r = await c.get(
                    f"{settings.AGENT_ENGINE_URL}/agents/available-tools",
                    headers=headers,
                )
                if r.status_code == 200:
                    data = r.json()
                    count = len(data.get("tools", [])) if isinstance(data, dict) else len(data) if isinstance(data, list) else 0
                    if count:
                        ctx["tools_summary"] = f"{count} tools available"
        except Exception as e:
            logger.debug(f"[CTX] tools fetch: {e}")

    async def _fetch_memory():
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as c:
                r = await c.post(
                    f"{settings.MEMORY_SERVICE_URL}/memory/search",
                    json={"query": "user preferences role company", "user_id": user_id, "limit": 5},
                    headers=headers,
                )
                if r.status_code == 200:
                    results = r.json().get("results", [])
                    if results:
                        facts = [m.get("content", "")[:200] for m in results[:5]]
                        ctx["memory_facts"] = " | ".join(f for f in facts if f)
        except Exception as e:
            logger.debug(f"[CTX] memory fetch: {e}")

    await asyncio.gather(
        _fetch_agents(), _fetch_tools(), _fetch_memory(),
        return_exceptions=True,
    )
    return ctx


async def store_memory(
    user_id: str,
    content: str,
    metadata: dict | None = None,
) -> bool:
    """Store a user fact in memory service. Fire-and-forget."""
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as c:
            resp = await c.post(
                f"{settings.MEMORY_SERVICE_URL}/memory/ingest",
                json={
                    "user_id": user_id,
                    "source": "agent_architect",
                    "content": content,
                    "metadata": metadata or {"type": "user_fact", "origin": "agent_architect"},
                },
            )
            return resp.status_code in (200, 201)
    except Exception as e:
        logger.debug(f"[CTX] memory store failed: {e}")
        return False
