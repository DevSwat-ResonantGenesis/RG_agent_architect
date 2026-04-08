"""
RG Agent Architect — Tool Executor

Executes tool calls from the LLM agent loop against the Agent Engine API.
Each function takes parsed arguments and returns a string result that gets
fed back into the LLM conversation as a tool response.
"""
import json
import logging

import httpx

from ..config import settings
from .runner import run_agent_full, fetch_agent_sessions, create_schedule, parse_schedule_from_message

logger = logging.getLogger(__name__)

AGENT_ENGINE_URL = settings.AGENT_ENGINE_URL


async def execute_tool(
    tool_name: str,
    arguments: dict,
    headers: dict[str, str],
    agents_cache: list[dict],
) -> str:
    """Execute a tool call and return the result as a string for the LLM.

    Args:
        tool_name: Name of the tool to execute
        arguments: Parsed JSON arguments from the LLM
        headers: Auth headers for API calls
        agents_cache: Cached list of user's agents (from workspace context)

    Returns:
        String result to feed back to the LLM
    """
    logger.info(f"🔧 [TOOL] Executing: {tool_name}({json.dumps(arguments)[:200]})")
    print(f"[TOOL_EXEC] {tool_name}({json.dumps(arguments)[:150]})", flush=True)

    try:
        if tool_name == "list_agents":
            return await _list_agents(headers, agents_cache)
        elif tool_name == "get_agent_details":
            return await _get_agent_details(arguments, headers, agents_cache)
        elif tool_name == "delete_agent":
            return await _delete_agent(arguments, headers, agents_cache)
        elif tool_name == "create_agent":
            return await _create_agent(arguments, headers)
        elif tool_name == "run_agent":
            return await _run_agent(arguments, headers, agents_cache)
        elif tool_name == "modify_agent":
            return await _modify_agent(arguments, headers, agents_cache)
        elif tool_name == "schedule_agent":
            return await _schedule_agent(arguments, headers, agents_cache)
        elif tool_name == "stop_agent":
            return await _stop_agent(arguments, headers, agents_cache)
        elif tool_name == "get_agent_sessions":
            return await _get_agent_sessions(arguments, headers, agents_cache)
        elif tool_name == "list_platform_tools":
            return await _list_platform_tools(headers)
        elif tool_name == "respond_to_user":
            # This is handled by the orchestrator loop, not here
            return "respond_to_user is a terminal action — handled by orchestrator."
        else:
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        logger.error(f"[TOOL] {tool_name} failed: {e}")
        return f"Error executing {tool_name}: {e}"


def _find_agent(name: str, agents: list[dict]) -> dict | None:
    """Find agent by name (case-insensitive, fuzzy)."""
    name_lower = name.lower().strip()
    # Exact match
    for a in agents:
        if (a.get("name") or "").lower() == name_lower:
            return a
    # Partial match
    for a in agents:
        if name_lower in (a.get("name") or "").lower():
            return a
    # Word match
    for a in agents:
        agent_words = (a.get("name") or "").lower().replace("_", " ").split()
        if any(w in name_lower for w in agent_words if len(w) > 3):
            return a
    return None


async def _list_agents(headers: dict, agents_cache: list[dict]) -> str:
    """List all agents in workspace."""
    # Refresh from API for latest data
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
            r = await c.get(f"{AGENT_ENGINE_URL}/agents/", headers=headers)
            if r.status_code == 200:
                data = r.json()
                agents = data if isinstance(data, list) else data.get("agents", [])
            else:
                agents = agents_cache
    except Exception:
        agents = agents_cache

    if not agents:
        return json.dumps({"count": 0, "agents": [], "message": "No agents in workspace yet."})

    result = []
    for a in agents[:20]:
        result.append({
            "name": a.get("name", "?"),
            "id": a.get("id"),
            "model": a.get("model", "?"),
            "provider": a.get("provider", "?"),
            "tools": a.get("tools", [])[:6],
            "is_active": a.get("is_active", False),
            "description": (a.get("description") or "")[:100],
        })
    return json.dumps({"count": len(agents), "agents": result})


async def _get_agent_details(args: dict, headers: dict, agents_cache: list[dict]) -> str:
    """Get detailed info about a specific agent including recent sessions."""
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, agents_cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found in workspace."})

    agent_id = agent["id"]
    info = {
        "name": agent.get("name"),
        "id": agent_id,
        "model": agent.get("model"),
        "provider": agent.get("provider"),
        "tools": agent.get("tools", []),
        "is_active": agent.get("is_active"),
        "description": agent.get("description"),
        "mode": agent.get("mode"),
    }

    # Fetch recent sessions
    sessions = await fetch_agent_sessions(agent_id, headers)
    if sessions:
        info["recent_sessions"] = [
            {
                "id": str(s.get("id", "?"))[:12],
                "status": s.get("status"),
                "goal": (s.get("current_goal") or "")[:80],
                "loops": s.get("loop_count", 0),
                "error": (s.get("error_message") or "")[:100] if s.get("error_message") else None,
            }
            for s in sessions[:5]
        ]
    else:
        info["recent_sessions"] = []

    return json.dumps(info)


async def _delete_agent(args: dict, headers: dict, agents_cache: list[dict]) -> str:
    """Delete an agent permanently."""
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, agents_cache)
    if not agent:
        # Try fresh fetch
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
                r = await c.get(f"{AGENT_ENGINE_URL}/agents/", headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    fresh = data if isinstance(data, list) else data.get("agents", [])
                    agent = _find_agent(agent_name, fresh)
        except Exception:
            pass

    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found. Cannot delete."})

    agent_id = agent["id"]
    name = agent.get("name", agent_name)

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            resp = await c.delete(f"{AGENT_ENGINE_URL}/agents/{agent_id}", headers=headers)
            print(f"[TOOL_EXEC] DELETE /agents/{agent_id} → {resp.status_code}", flush=True)
            if resp.status_code in (200, 204):
                return json.dumps({"success": True, "deleted": name, "id": agent_id})
            else:
                return json.dumps({"error": f"Delete API returned {resp.status_code}: {resp.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": f"Delete failed: {e}"})


async def _create_agent(args: dict, headers: dict) -> str:
    """Create a new agent via Agent Engine API."""
    payload = {
        "name": args.get("name", "New Agent"),
        "description": args.get("description", ""),
        "system_prompt": args.get("system_prompt", f"You are {args.get('name', 'an agent')}. {args.get('description', '')}"),
        "goal": args.get("goal", ""),
        "provider": args.get("provider", "groq"),
        "model": args.get("model", "llama-3.3-70b-versatile"),
        "tools": args.get("tools", []),
        "temperature": args.get("temperature", 0.6),
        "max_tokens": args.get("max_tokens", 4096),
        "mode": args.get("mode", "governed"),
        "is_active": True,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
            resp = await c.post(
                f"{AGENT_ENGINE_URL}/agents/",
                headers={**headers, "Content-Type": "application/json"},
                json=payload,
            )
            print(f"[TOOL_EXEC] POST /agents/ → {resp.status_code}", flush=True)
            if resp.status_code in (200, 201):
                data = resp.json()
                return json.dumps({
                    "success": True,
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "model": data.get("model"),
                    "tools": data.get("tools", []),
                })
            else:
                return json.dumps({"error": f"Create failed ({resp.status_code}): {resp.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": f"Create failed: {e}"})


async def _run_agent(args: dict, headers: dict, agents_cache: list[dict]) -> str:
    """Execute an agent immediately."""
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, agents_cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})

    agent_id = agent["id"]
    name = agent.get("name", agent_name)
    task = agent.get("description") or agent.get("goal") or f"Run {name}"

    result = await run_agent_full(agent_id, name, task, headers)
    return json.dumps({
        "agent": name,
        "status": result.get("status", "unknown"),
        "steps": result.get("steps"),
        "output": str(result.get("output", ""))[:500],
        "error": result.get("error"),
    })


async def _modify_agent(args: dict, headers: dict, agents_cache: list[dict]) -> str:
    """Modify an existing agent's configuration."""
    agent_name = args.get("agent_name", "")
    changes = args.get("changes", {})
    agent = _find_agent(agent_name, agents_cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})

    if not changes:
        return json.dumps({"error": "No changes specified."})

    agent_id = agent["id"]
    name = agent.get("name", agent_name)

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            resp = await c.patch(
                f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                headers={**headers, "Content-Type": "application/json"},
                json=changes,
            )
            if resp.status_code == 405:
                # Try PUT with full agent data
                merged = {**agent, **changes}
                resp = await c.put(
                    f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                    headers={**headers, "Content-Type": "application/json"},
                    json=merged,
                )
            print(f"[TOOL_EXEC] PATCH /agents/{agent_id} → {resp.status_code}", flush=True)
            if resp.status_code in (200, 204):
                return json.dumps({"success": True, "agent": name, "applied_changes": changes})
            else:
                return json.dumps({"error": f"Modify failed ({resp.status_code}): {resp.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": f"Modify failed: {e}"})


async def _schedule_agent(args: dict, headers: dict, agents_cache: list[dict]) -> str:
    """Set up recurring schedule for an agent."""
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, agents_cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})

    agent_id = agent["id"]
    name = agent.get("name", agent_name)
    interval = args.get("interval_seconds", 86400)
    cron = args.get("cron_expression")
    goal = f"Automated recurring execution of {name}"

    ok = await create_schedule(agent_id, name, interval, cron, goal, headers)
    if ok:
        label = {3600: "hourly", 86400: "daily", 604800: "weekly"}.get(interval, f"every {interval}s")
        return json.dumps({"success": True, "agent": name, "schedule": label})
    return json.dumps({"error": f"Failed to create schedule for {name}"})


async def _get_agent_sessions(args: dict, headers: dict, agents_cache: list[dict]) -> str:
    """Get recent execution sessions for an agent."""
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, agents_cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})

    agent_id = agent["id"]
    sessions = await fetch_agent_sessions(agent_id, headers, limit=8)
    if not sessions:
        return json.dumps({"agent": agent.get("name"), "sessions": [], "message": "No sessions found."})

    result = []
    for s in sessions:
        result.append({
            "id": str(s.get("id", "?"))[:12],
            "status": s.get("status"),
            "goal": (s.get("current_goal") or "")[:120],
            "loops": s.get("loop_count", 0),
            "tokens": s.get("total_tokens_used", 0),
            "error": (s.get("error_message") or "")[:200] if s.get("error_message") else None,
            "created": s.get("created_at"),
        })
    return json.dumps({"agent": agent.get("name"), "total_sessions": len(result), "sessions": result})


async def _list_platform_tools(headers: dict) -> str:
    """List all available platform tools from Agent Engine."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.get(f"{AGENT_ENGINE_URL}/agents/tools/list", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                tools = data if isinstance(data, list) else data.get("tools", [])
                # Group by category for readability
                by_cat: dict[str, list[str]] = {}
                for t in tools:
                    cat = t.get("category", "other") if isinstance(t, dict) else "other"
                    name = t.get("name", str(t)) if isinstance(t, dict) else str(t)
                    by_cat.setdefault(cat, []).append(name)
                return json.dumps({"total": len(tools), "by_category": by_cat})
    except Exception as e:
        logger.warning(f"[TOOL] list_platform_tools failed: {e}")

    # Fallback: return a curated list
    return json.dumps({"total": "200+", "categories": [
        "SEARCH: web_search, fetch_url, read_webpage, news_search, reddit_search, youtube_search, deep_research, wikipedia, places_search, image_search",
        "MEMORY: memory_read, memory_write, memory_search",
        "CODE: execute_code, code_visualizer_scan, code_visualizer_functions, code_visualizer_trace",
        "AGENTS: agents_list, agents_create, agents_start, agents_sessions, agents_update, schedule_agent",
        "MEDIA: generate_image, generate_audio, generate_music",
        "INTEGRATIONS: gmail_send, gmail_read, slack_send, slack_read, google_calendar, google_drive, figma",
        "DEVELOPER: execute_code, http_request, external_http_request",
        "GITHUB: github_create_repo, github_list_repos, github_list_files, github_download_file, github_upload_file, github_pull_request, github_issue",
        "GIT: git_clone, git_branch, git_push, git_pull",
        "EMAIL: send_email",
        "PLATFORM_API: platform_api, discover_services, discover_api",
        "UTILITIES: weather, stock_crypto, generate_chart, get_current_time",
        "TOOL_MANAGEMENT: check_tool_exists, auto_build_tool, list_built_tools, execute_built_tool",
    ]})


async def _stop_agent(args: dict, headers: dict, agents_cache: list[dict]) -> str:
    """Deactivate an agent."""
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, agents_cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})

    agent_id = agent["id"]
    name = agent.get("name", agent_name)

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            resp = await c.patch(
                f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                headers={**headers, "Content-Type": "application/json"},
                json={"is_active": False},
            )
            if resp.status_code in (200, 204):
                return json.dumps({"success": True, "agent": name, "status": "deactivated"})
            else:
                return json.dumps({"error": f"Stop failed ({resp.status_code}): {resp.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": f"Stop failed: {e}"})
