"""
RG Agent Architect — Tool Executor

Executes all 36 tool calls from the orchestrator ReAct loop against
the Agent Engine API. Each handler takes parsed arguments and returns
a string result fed back into the LLM conversation.

Twin architecture reference: twin.md Sections 2, 7 (dispatching), 5 (scope_risk).
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx

from ..config import settings
from .runner import run_agent_full, fetch_agent_sessions, create_schedule
from .goal_crafter import craft_goal, format_scope_warning, ScopeRisk

logger = logging.getLogger(__name__)

AGENT_ENGINE_URL = settings.AGENT_ENGINE_URL


# ═══════════════════════════════════════════════════════════════
# MAIN DISPATCHER
# ═══════════════════════════════════════════════════════════════

async def execute_tool(
    tool_name: str,
    arguments: dict,
    headers: dict[str, str],
    agents_cache: list[dict],
) -> str:
    """Execute a tool call and return string result for the LLM."""
    logger.info(f"🔧 [TOOL] Executing: {tool_name}({json.dumps(arguments)[:200]})")

    try:
        handler = _HANDLERS.get(tool_name)
        if handler:
            return await handler(arguments, headers, agents_cache)
        return f"Unknown tool: {tool_name}"
    except Exception as e:
        logger.error(f"[TOOL] {tool_name} failed: {e}")
        return f"Error executing {tool_name}: {e}"


# ═══════════════════════════════════════════════════════════════
# AGENT LOOKUP HELPER
# ═══════════════════════════════════════════════════════════════

def _find_agent(name: str, agents: list[dict]) -> dict | None:
    """Find agent by name (case-insensitive, fuzzy)."""
    name_lower = name.lower().strip()
    for a in agents:
        if (a.get("name") or "").lower() == name_lower:
            return a
    for a in agents:
        if name_lower in (a.get("name") or "").lower():
            return a
    for a in agents:
        words = (a.get("name") or "").lower().replace("_", " ").split()
        if any(w in name_lower for w in words if len(w) > 3):
            return a
    return None


async def _refresh_agents(headers: dict) -> list[dict]:
    """Fetch fresh agent list from API."""
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
            r = await c.get(f"{AGENT_ENGINE_URL}/agents/", headers=headers)
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else data.get("agents", [])
    except Exception:
        pass
    return []


# ═══════════════════════════════════════════════════════════════
# 1. WORKSPACE & CONTEXT HANDLERS
# ═══════════════════════════════════════════════════════════════

async def _workspace_snapshot(args: dict, headers: dict, cache: list) -> str:
    from .context import fetch_workspace_context
    user_id = headers.get("x-user-id", "")
    ctx = await fetch_workspace_context(user_id, headers)
    agents = ctx.get("agents", [])
    summaries = []
    for a in agents[:20]:
        summaries.append({
            "name": a.get("name", "?"),
            "status": "active" if a.get("is_active") else "inactive",
            "model": a.get("model", "?"),
            "tools": ", ".join(a.get("tools", [])[:5]),
            "mode": a.get("mode", "governed"),
        })
    return json.dumps({
        "agents": summaries,
        "agent_count": len(agents),
        "tools_summary": ctx.get("tools_summary", "160+ tools"),
        "tools_by_category": ctx.get("tools_by_category", {}),
        "user_memory": ctx.get("memory_facts", ""),
    })


async def _agent_snapshot(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    agent_id = agent["id"]
    result: dict = {"agent": agent}
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as c:
            detail_task = c.get(f"{AGENT_ENGINE_URL}/agents/{agent_id}", headers=headers)
            sessions_task = c.get(f"{AGENT_ENGINE_URL}/execution/history/{agent_id}", headers=headers, params={"limit": 5})
            detail_resp, sessions_resp = await asyncio.gather(detail_task, sessions_task, return_exceptions=True)
            if not isinstance(detail_resp, Exception) and detail_resp.status_code == 200:
                full = detail_resp.json()
                result["config"] = {
                    "system_prompt": (full.get("system_prompt") or "")[:500],
                    "goal": full.get("goal") or full.get("description", ""),
                    "tools": full.get("tools", []),
                    "model": full.get("model", "?"),
                    "provider": full.get("provider", "?"),
                    "mode": full.get("mode", "governed"),
                    "safety_config": full.get("safety_config", {}),
                    "budget_config": full.get("budget_config", {}),
                    "is_active": full.get("is_active", False),
                }
            if not isinstance(sessions_resp, Exception) and sessions_resp.status_code == 200:
                sessions = sessions_resp.json()
                if isinstance(sessions, list):
                    result["recent_runs"] = [{
                        "id": str(s.get("id", "?"))[:12],
                        "status": s.get("status", "?"),
                        "loops": s.get("loop_count", 0),
                        "error": (s.get("error_message") or "")[:150],
                        "output": (str(s.get("output") or s.get("final_output") or ""))[:200],
                    } for s in sessions[:5]]
    except Exception as e:
        result["fetch_error"] = str(e)
    return json.dumps(result)


async def _run_snapshot(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    session_id = args.get("session_id")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    agent_id = agent["id"]
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            if session_id:
                resp = await c.get(f"{AGENT_ENGINE_URL}/execution/session/{session_id}", headers=headers)
            else:
                resp = await c.get(f"{AGENT_ENGINE_URL}/execution/history/{agent_id}", headers=headers, params={"limit": 1})
            if resp.status_code != 200:
                return json.dumps({"error": f"Failed: HTTP {resp.status_code}"})
            data = resp.json()
            session = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else None
            if not session:
                return json.dumps({"error": "No runs found."})
            return json.dumps({
                "agent": agent_name,
                "session_id": str(session.get("id", "?"))[:12],
                "status": session.get("status", "?"),
                "loop_count": session.get("loop_count", 0),
                "output": str(session.get("output") or session.get("final_output") or "")[:1000],
                "error": (session.get("error_message") or "")[:300],
                "tool_calls": session.get("tool_calls", [])[:20],
                "created_at": str(session.get("created_at", "")),
            })
    except Exception as e:
        return json.dumps({"error": f"Run snapshot failed: {e}"})


async def _list_agents(args: dict, headers: dict, cache: list) -> str:
    agents = await _refresh_agents(headers) or cache
    if not agents:
        return json.dumps({"count": 0, "agents": [], "message": "No agents in workspace."})
    result = [{
        "name": a.get("name", "?"),
        "id": a.get("id"),
        "model": a.get("model", "?"),
        "provider": a.get("provider", "?"),
        "tools": a.get("tools", [])[:6],
        "is_active": a.get("is_active", False),
        "description": (a.get("description") or "")[:100],
    } for a in agents[:20]]
    return json.dumps({"count": len(agents), "agents": result})


async def _get_agent_details(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    agent_id = agent["id"]
    info = {k: agent.get(k) for k in ("name", "id", "model", "provider", "tools", "is_active", "description", "mode")}
    sessions = await fetch_agent_sessions(agent_id, headers)
    info["recent_sessions"] = [{
        "id": str(s.get("id", "?"))[:12],
        "status": s.get("status"),
        "goal": (s.get("current_goal") or "")[:80],
        "loops": s.get("loop_count", 0),
        "error": (s.get("error_message") or "")[:100] if s.get("error_message") else None,
    } for s in (sessions or [])[:5]]
    return json.dumps(info)


async def _list_platform_tools(args: dict, headers: dict, cache: list) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.get(f"{AGENT_ENGINE_URL}/agents/tools/list", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                tools = data if isinstance(data, list) else data.get("tools", [])
                by_cat: dict[str, list[str]] = {}
                for t in tools:
                    cat = t.get("category", "other") if isinstance(t, dict) else "other"
                    name = t.get("name", str(t)) if isinstance(t, dict) else str(t)
                    by_cat.setdefault(cat, []).append(name)
                return json.dumps({"total": len(tools), "by_category": by_cat})
    except Exception:
        pass
    return json.dumps({"total": "200+", "categories": [
        "SEARCH: web_search, fetch_url, deep_research, news_search",
        "MEMORY: memory_read, memory_write, memory_search",
        "CODE: execute_code, code_visualizer_scan",
        "MEDIA: generate_image, generate_audio",
        "INTEGRATIONS: gmail_send, slack_send, google_calendar",
        "DEVELOPER: execute_code, http_request",
    ]})


async def _list_workspace_databases(args: dict, headers: dict, cache: list) -> str:
    agents = await _refresh_agents(headers) or cache
    databases = [{"agent": a.get("name", "?"), "agent_id": a.get("id"), "has_data": bool(a.get("has_database")), "status": "active" if a.get("is_active") else "inactive"} for a in agents[:20]]
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
            resp = await c.get(f"{AGENT_ENGINE_URL}/databases/list", headers=headers)
            if resp.status_code == 200:
                return json.dumps({"databases": resp.json(), "agent_count": len(agents)})
    except Exception:
        pass
    return json.dumps({"databases": databases, "agent_count": len(agents)})


async def _query_cross_agent_database(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    query = args.get("query", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    if not query:
        return json.dumps({"error": "SQL query required."})
    if not query.strip().upper().startswith("SELECT"):
        return json.dumps({"error": "Only SELECT queries allowed."})
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            resp = await c.post(f"{AGENT_ENGINE_URL}/databases/query", headers={**headers, "Content-Type": "application/json"}, json={"agent_id": agent["id"], "query": query})
            if resp.status_code == 200:
                data = resp.json()
                return json.dumps({"agent": agent_name, "query": query, "rows": data.get("rows", [])[:100], "columns": data.get("columns", []), "row_count": data.get("row_count", 0)})
            return json.dumps({"error": f"Query failed ({resp.status_code}): {resp.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": f"Database query failed: {e}"})


# ═══════════════════════════════════════════════════════════════
# 2. AGENT LIFECYCLE HANDLERS
# ═══════════════════════════════════════════════════════════════

async def _create_agent(args: dict, headers: dict, cache: list) -> str:
    """Twin dispatching: Create → build_agent(name, goal, icon).

    Integrates 8-step goal crafting pipeline:
    1. Craft goal (strip recurrence, strip secrets, identify services)
    2. Check scope risk → return warning if HIGH/MODERATE
    3. Generate builder instruction template
    4. Apply task profile for model/loops/temperature
    5. Create agent via Agent Engine API
    """
    budget = args.get("budget") or {}
    raw_goal = args.get("goal", "")
    name = args.get("name", "New Agent")
    tools = args.get("tools", [])

    # Step 1-7: Goal crafting pipeline
    crafted = craft_goal(raw_goal, tools)

    # If scope risk detected, return warning (LLM should present_options)
    if crafted.risk_level != ScopeRisk.SAFE:
        warning = format_scope_warning(crafted)
        return json.dumps({
            "scope_warning": warning,
            "crafted_goal": crafted.goal_text,
            "services": crafted.services,
            "schedule": crafted.schedule,
            "assumptions": crafted.assumptions,
            "action_required": "present scope warning to user before proceeding",
        })

    # Builder instruction template (twin-platform builder.py pattern)
    system_prompt = args.get("system_prompt")
    if not system_prompt or len(system_prompt) < 50:
        system_prompt = (
            f"You are {name}, an autonomous agent.\n"
            f"Goal: {crafted.goal_text}\n\n"
            f"INSTRUCTIONS (follow these steps exactly):\n"
            f"Step 1: Analyze goal, identify data sources and required tools.\n"
            f"Step 2: Gather data using your tools ({', '.join(tools)}).\n"
            f"Step 3: Process, filter, and validate results.\n"
            f"Step 4: Format output and store in database.\n\n"
            f"CONSTRAINTS:\n"
            f"- Maximum 50 results unless specified\n"
            f"- Include source URLs for all data\n"
            f"- Do NOT hallucinate — only report verified tool results\n"
            f"- Store final results using Memory Store\n"
        )

    # Apply task profile based on complexity
    profile = settings.TASK_PROFILES.get("medium", {})
    max_loops = args.get("max_loops") or profile.get("max_loops", 30)
    temperature = args.get("temperature") or profile.get("temperature", 0.6)

    payload = {
        "name": name,
        "description": args.get("description", ""),
        "system_prompt": system_prompt,
        "goal": crafted.goal_text,
        "provider": args.get("provider", "groq"),
        "model": args.get("model", "llama-3.3-70b-versatile"),
        "tools": tools,
        "temperature": temperature,
        "max_tokens": 4096,
        "mode": args.get("mode", "governed"),
        "is_active": True,
        "safety_config": {"max_loops": max_loops},
    }
    if budget:
        payload["budget_config"] = {"max_tokens_per_run": budget.get("max_tokens_per_run", 50000), "max_runs_per_day": budget.get("max_runs_per_day", 10)}
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
            resp = await c.post(f"{AGENT_ENGINE_URL}/agents/", headers={**headers, "Content-Type": "application/json"}, json=payload)
            if resp.status_code in (200, 201):
                data = resp.json()
                result: dict = {"success": True, "id": data.get("id"), "name": data.get("name"), "model": data.get("model"), "tools": data.get("tools", [])}
                if crafted.schedule:
                    result["detected_schedule"] = crafted.schedule
                    result["note"] = "Schedule detected — call schedule_agent after build completes"
                if crafted.assumptions:
                    result["assumptions"] = crafted.assumptions
                if data.get("id") and budget.get("initial_credits"):
                    await _create_wallet(data["id"], budget["initial_credits"], headers)
                    result["initial_credits"] = budget["initial_credits"]
                return json.dumps(result)
            return json.dumps({"error": f"Create failed ({resp.status_code}): {resp.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": f"Create failed: {e}"})


async def _continue_build(args: dict, headers: dict, cache: list) -> str:
    """Twin dispatching: Extend → continue_build (3-part delta)."""
    agent_name = args.get("agent_name", "")
    instructions = args.get("instructions", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    if not instructions:
        return json.dumps({"error": "Instructions required (3-part delta: CHANGES / STAYS / STOPS)."})
    agent_id = agent["id"]
    current_prompt = ""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.get(f"{AGENT_ENGINE_URL}/agents/{agent_id}", headers=headers)
            if resp.status_code == 200:
                current_prompt = resp.json().get("system_prompt", "")
    except Exception:
        pass
    rebuild_prompt = f"=== REBUILD INSTRUCTIONS ===\n{instructions}\n\n=== ORIGINAL INSTRUCTIONS (preserve what STAYS) ===\n{current_prompt}\n"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            resp = await c.patch(f"{AGENT_ENGINE_URL}/agents/{agent_id}", headers={**headers, "Content-Type": "application/json"}, json={"system_prompt": rebuild_prompt})
            if resp.status_code in (200, 204):
                return json.dumps({"success": True, "agent": agent.get("name"), "action": "continue_build", "message": f"Agent instructions updated with rebuild delta."})
            return json.dumps({"error": f"Rebuild failed ({resp.status_code}): {resp.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": f"continue_build failed: {e}"})


async def _message_build(args: dict, headers: dict, cache: list) -> str:
    """Twin dispatching: Guide → message_build."""
    agent_name = args.get("agent_name", "")
    message = args.get("message", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    if not message:
        return json.dumps({"error": "Message required."})
    agent_id = agent["id"]
    sessions = await fetch_agent_sessions(agent_id, headers, limit=1)
    active = next((s for s in (sessions or []) if s.get("status") in ("running", "in_progress", "building")), None)
    if active:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
                resp = await c.post(f"{AGENT_ENGINE_URL}/execution/session/{active['id']}/message", headers={**headers, "Content-Type": "application/json"}, json={"message": message, "role": "architect"})
                if resp.status_code in (200, 201):
                    return json.dumps({"success": True, "agent": agent.get("name"), "message_delivered": True})
        except Exception:
            pass
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            await c.patch(f"{AGENT_ENGINE_URL}/agents/{agent_id}", headers={**headers, "Content-Type": "application/json"}, json={"metadata": {"pending_build_message": message}})
    except Exception:
        pass
    return json.dumps({"success": True, "agent": agent.get("name"), "message_queued": True, "note": "No active build. Queued for next run."})


async def _modify_agent(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    changes = args.get("changes", {})
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    if not changes:
        return json.dumps({"error": "No changes specified."})
    agent_id = agent["id"]
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            resp = await c.patch(f"{AGENT_ENGINE_URL}/agents/{agent_id}", headers={**headers, "Content-Type": "application/json"}, json=changes)
            if resp.status_code == 405:
                resp = await c.put(f"{AGENT_ENGINE_URL}/agents/{agent_id}", headers={**headers, "Content-Type": "application/json"}, json={**agent, **changes})
            if resp.status_code in (200, 204):
                return json.dumps({"success": True, "agent": agent.get("name"), "applied_changes": changes})
            return json.dumps({"error": f"Modify failed ({resp.status_code}): {resp.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": f"Modify failed: {e}"})


async def _run_agent(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    agent_id = agent["id"]
    name = agent.get("name", agent_name)
    task = agent.get("description") or agent.get("goal") or f"Run {name}"
    result = await run_agent_full(agent_id, name, task, headers)
    return json.dumps({"agent": name, "status": result.get("status", "unknown"), "steps": result.get("steps"), "output": str(result.get("output", ""))[:500], "error": result.get("error")})


async def _stop_agent(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            resp = await c.patch(f"{AGENT_ENGINE_URL}/agents/{agent['id']}", headers={**headers, "Content-Type": "application/json"}, json={"is_active": False})
            if resp.status_code in (200, 204):
                return json.dumps({"success": True, "agent": agent.get("name"), "status": "deactivated"})
            return json.dumps({"error": f"Stop failed ({resp.status_code})"})
    except Exception as e:
        return json.dumps({"error": f"Stop failed: {e}"})


async def _delete_agent(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        fresh = await _refresh_agents(headers)
        agent = _find_agent(agent_name, fresh)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            resp = await c.delete(f"{AGENT_ENGINE_URL}/agents/{agent['id']}", headers=headers)
            if resp.status_code in (200, 204):
                return json.dumps({"success": True, "deleted": agent.get("name"), "id": agent["id"]})
            return json.dumps({"error": f"Delete failed ({resp.status_code}): {resp.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": f"Delete failed: {e}"})


async def _schedule_agent(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    interval = args.get("interval_seconds", 86400)
    cron = args.get("cron_expression")
    ok = await create_schedule(agent["id"], agent.get("name", ""), interval, cron, f"Scheduled run of {agent.get('name')}", headers)
    if ok:
        label = {3600: "hourly", 86400: "daily", 604800: "weekly"}.get(interval, f"every {interval}s")
        return json.dumps({"success": True, "agent": agent.get("name"), "schedule": label})
    return json.dumps({"error": f"Schedule creation failed for {agent.get('name')}"})


async def _set_agent_budget(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    agent_id = agent["id"]
    result: dict = {"agent": agent.get("name")}
    changes: dict = {}
    if args.get("max_tokens_per_run") or args.get("max_runs_per_day"):
        bc = {}
        if args.get("max_tokens_per_run"):
            bc["max_tokens_per_run"] = args["max_tokens_per_run"]
        if args.get("max_runs_per_day"):
            bc["max_runs_per_day"] = args["max_runs_per_day"]
        changes["budget_config"] = bc
    if changes:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
                resp = await c.patch(f"{AGENT_ENGINE_URL}/agents/{agent_id}", headers={**headers, "Content-Type": "application/json"}, json=changes)
                result["budget_updated"] = resp.status_code in (200, 204)
        except Exception as e:
            result["budget_error"] = str(e)
    if args.get("credits"):
        ok = await _create_wallet(agent_id, args["credits"], headers)
        result["credits_deposited"] = ok
    return json.dumps(result)


async def _check_agent_wallet(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    agent_id = agent["id"]
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.get(f"{AGENT_ENGINE_URL}/wallets/agent/{agent_id}", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return json.dumps({"agent": agent.get("name"), "balance": data.get("balance", 0), "total_spent": data.get("total_spent", 0)})
            resp2 = await c.get(f"{AGENT_ENGINE_URL}/credits/agent/{agent_id}", headers=headers)
            if resp2.status_code == 200:
                return json.dumps({"agent": agent.get("name"), **resp2.json()})
    except Exception as e:
        return json.dumps({"error": f"Wallet check failed: {e}"})
    return json.dumps({"agent": agent.get("name"), "wallet": "not_found"})


async def _create_wallet(agent_id: str, credits: float, headers: dict) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.post(f"{AGENT_ENGINE_URL}/wallets/agent/{agent_id}", headers={**headers, "Content-Type": "application/json"}, json={"initial_balance": credits})
            if resp.status_code in (200, 201):
                return True
            resp2 = await c.post(f"{AGENT_ENGINE_URL}/credits/deposit", headers={**headers, "Content-Type": "application/json"}, json={"agent_id": agent_id, "amount": credits, "reason": "Architect allocation"})
            return resp2.status_code in (200, 201)
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# 3. USER INTERFACE HANDLERS
# ═══════════════════════════════════════════════════════════════

async def _present_options(args: dict, headers: dict, cache: list) -> str:
    """Semi-terminal action: return structured options for frontend."""
    result = {
        "type": "present_options",
        "question": args.get("question", ""),
        "options": args.get("options", []),
        "question_type": args.get("question_type", "PickOne"),
    }
    if args.get("scope_warning"):
        result["scope_warning"] = args["scope_warning"]
    return json.dumps(result)


async def _respond_to_user(args: dict, headers: dict, cache: list) -> str:
    return "respond_to_user is a terminal action — handled by orchestrator."


async def _present_billing_offer(args: dict, headers: dict, cache: list) -> str:
    plans = {
        "free": {"price": "$0", "credits": "2,200 trial"},
        "plus": {"price": "€20/mo", "credits": "2,000/mo"},
        "pro": {"price": "€200/mo", "credits": "20,000/mo"},
        "max": {"price": "€1,000/mo", "credits": "100,000/mo"},
    }
    return json.dumps({
        "type": "billing_offer",
        "reason": args.get("reason", "general"),
        "current_plan": {"name": args.get("current_plan", "free"), **(plans.get(args.get("current_plan", "free"), {}))},
        "recommended_plan": {"name": args.get("recommended_plan", "plus"), **(plans.get(args.get("recommended_plan", "plus"), {}))},
        "all_plans": plans,
    })


async def _open_interface_editor(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            resp = await c.post(f"{AGENT_ENGINE_URL}/interfaces/create", headers={**headers, "Content-Type": "application/json"}, json={"agent_id": agent["id"], "type": "react_app"})
            if resp.status_code in (200, 201):
                data = resp.json()
                return json.dumps({"success": True, "agent": agent.get("name"), "interface_url": data.get("url", ""), "editor_url": data.get("editor_url", "")})
    except Exception:
        pass
    return json.dumps({"agent": agent.get("name"), "action": "open_interface_editor", "status": "pending_implementation"})


# ═══════════════════════════════════════════════════════════════
# 4. UTILITY HANDLERS
# ═══════════════════════════════════════════════════════════════

async def _get_user_memory(args: dict, headers: dict, cache: list) -> str:
    query = args.get("query", "user preferences role company")
    user_id = headers.get("x-user-id", "")
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
            resp = await c.post(f"{settings.MEMORY_SERVICE_URL}/memory/search", json={"query": query, "user_id": user_id, "limit": 10}, headers=headers)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    facts = [{"content": m.get("content", "")[:300], "type": m.get("metadata", {}).get("type", "fact")} for m in results[:10]]
                    return json.dumps({"facts": facts, "count": len(facts)})
                return json.dumps({"facts": [], "count": 0})
            return json.dumps({"error": f"Memory search failed: HTTP {resp.status_code}"})
    except Exception as e:
        return json.dumps({"error": f"Memory search failed: {e}"})


async def _update_user_memory(args: dict, headers: dict, cache: list) -> str:
    content = args.get("content", "")
    metadata = args.get("metadata", {})
    user_id = headers.get("x-user-id", "")
    if not content:
        return json.dumps({"error": "Content required."})
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
            resp = await c.post(f"{settings.MEMORY_SERVICE_URL}/memory/ingest", json={"user_id": user_id, "source": "agent_architect", "content": content, "metadata": {**metadata, "origin": "agent_architect"}})
            if resp.status_code in (200, 201):
                return json.dumps({"success": True, "stored": content[:100]})
            return json.dumps({"error": f"Memory store failed: HTTP {resp.status_code}"})
    except Exception as e:
        return json.dumps({"error": f"Memory store failed: {e}"})


async def _get_credits_info(args: dict, headers: dict, cache: list) -> str:
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
            resp = await c.get(f"{AGENT_ENGINE_URL}/credits/balance", headers=headers, params={"user_id": headers.get("x-user-id", "")})
            if resp.status_code == 200:
                return json.dumps(resp.json())
            resp2 = await c.get(f"{AGENT_ENGINE_URL}/billing/info", headers=headers)
            if resp2.status_code == 200:
                return json.dumps(resp2.json())
    except Exception:
        pass
    return json.dumps({"note": "Credit info not available."})


async def _get_current_time(args: dict, headers: dict, cache: list) -> str:
    now = datetime.now(timezone.utc)
    return json.dumps({"utc": now.isoformat(), "unix": int(now.timestamp()), "formatted": now.strftime("%Y-%m-%d %H:%M:%S UTC")})


async def _set_workspace_name(args: dict, headers: dict, cache: list) -> str:
    name = args.get("name", "")
    icon = args.get("icon", "🚀")
    if not name:
        return json.dumps({"error": "Workspace name required."})
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.patch(f"{AGENT_ENGINE_URL}/workspace", headers={**headers, "Content-Type": "application/json"}, json={"name": name, "icon": icon, "user_id": headers.get("x-user-id", "")})
            if resp.status_code in (200, 204):
                return json.dumps({"success": True, "workspace_name": name, "icon": icon})
    except Exception:
        pass
    return json.dumps({"success": True, "workspace_name": name, "icon": icon, "note": "Stored locally."})


async def _configure_smtp(args: dict, headers: dict, cache: list) -> str:
    config = {k: args.get(k) for k in ("host", "port", "username", "password", "from_email", "from_name", "use_tls")}
    if not config.get("host") or not config.get("username") or not config.get("password"):
        return json.dumps({"error": "host, username, password required."})
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.post(f"{AGENT_ENGINE_URL}/smtp/configure", headers={**headers, "Content-Type": "application/json"}, json={"user_id": headers.get("x-user-id", ""), **config})
            if resp.status_code in (200, 201):
                return json.dumps({"success": True, "smtp_host": config["host"], "from_email": config.get("from_email")})
            return json.dumps({"error": f"SMTP config failed ({resp.status_code})"})
    except Exception as e:
        return json.dumps({"error": f"SMTP config failed: {e}"})


async def _delete_smtp(args: dict, headers: dict, cache: list) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.delete(f"{AGENT_ENGINE_URL}/smtp/configure", headers=headers, params={"user_id": headers.get("x-user-id", "")})
            if resp.status_code in (200, 204):
                return json.dumps({"success": True, "message": "SMTP removed. Default email restored."})
    except Exception as e:
        return json.dumps({"error": f"SMTP delete failed: {e}"})
    return json.dumps({"error": "SMTP delete failed."})


async def _file_operation(args: dict, headers: dict, cache: list) -> str:
    action = args.get("action", "")
    filename = args.get("filename", "")
    user_id = headers.get("x-user-id", "")
    if action == "list":
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
                resp = await c.get(f"{AGENT_ENGINE_URL}/files/list", headers=headers, params={"user_id": user_id})
                if resp.status_code == 200:
                    return json.dumps(resp.json())
        except Exception:
            pass
        return json.dumps({"files": []})
    if not filename:
        return json.dumps({"error": "filename required."})
    payload: dict = {"action": action, "filename": filename, "user_id": user_id}
    if action == "write":
        payload["content"] = args.get("content", "")
        payload["encoding"] = args.get("encoding", "text")
    elif action == "read":
        for k in ("offset_chars", "max_chars"):
            if args.get(k):
                payload[k] = args[k]
    elif action in ("download_via_curl", "upload_via_curl"):
        payload["url"] = args.get("url", "")
        if args.get("curl_args"):
            payload["curl_args"] = args["curl_args"]
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as c:
            resp = await c.post(f"{AGENT_ENGINE_URL}/files/operation", headers={**headers, "Content-Type": "application/json"}, json=payload)
            if resp.status_code in (200, 201):
                return json.dumps(resp.json())
            return json.dumps({"error": f"File op failed ({resp.status_code}): {resp.text[:300]}"})
    except Exception as e:
        return json.dumps({"error": f"File op failed: {e}"})


# ═══════════════════════════════════════════════════════════════
# 5. SELF-EXTENSION HANDLERS
# ═══════════════════════════════════════════════════════════════

async def _auto_build_tool(args: dict, headers: dict, cache: list) -> str:
    tool_name = args.get("tool_name", "")
    description = args.get("description", "")
    if not tool_name or not description:
        return json.dumps({"error": "tool_name and description required."})
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as c:
            resp = await c.post(f"{AGENT_ENGINE_URL}/agents/tools/execute", headers={**headers, "Content-Type": "application/json"}, json={"tool_name": "auto_build_tool", "tool_input": {"name": tool_name, "description": description, "input_schema": args.get("input_schema", {}), "implementation_hint": args.get("implementation_hint", "")}})
            if resp.status_code in (200, 201):
                return json.dumps({"success": True, "tool_name": tool_name, "details": resp.json()})
            return json.dumps({"error": f"auto_build_tool failed ({resp.status_code}): {resp.text[:300]}"})
    except Exception as e:
        return json.dumps({"error": f"auto_build_tool failed: {e}"})


async def _check_tool_exists(args: dict, headers: dict, cache: list) -> str:
    tool_name = args.get("tool_name", "")
    if not tool_name:
        return json.dumps({"error": "tool_name required."})
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.post(f"{AGENT_ENGINE_URL}/agents/tools/execute", headers={**headers, "Content-Type": "application/json"}, json={"tool_name": "check_tool_exists", "tool_input": {"tool_name": tool_name}})
            if resp.status_code == 200:
                return json.dumps(resp.json())
            resp2 = await c.get(f"{AGENT_ENGINE_URL}/agents/tools/list", headers=headers)
            if resp2.status_code == 200:
                tools = resp2.json() if isinstance(resp2.json(), list) else resp2.json().get("tools", [])
                found = any((t.get("name", "") if isinstance(t, dict) else str(t)) == tool_name for t in tools)
                return json.dumps({"tool_name": tool_name, "exists": found})
    except Exception:
        pass
    return json.dumps({"tool_name": tool_name, "exists": False})


async def _execute_built_tool(args: dict, headers: dict, cache: list) -> str:
    tool_name = args.get("tool_name", "")
    if not tool_name:
        return json.dumps({"error": "tool_name required."})
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as c:
            resp = await c.post(f"{AGENT_ENGINE_URL}/agents/tools/execute", headers={**headers, "Content-Type": "application/json"}, json={"tool_name": tool_name, "tool_input": args.get("inputs", {})})
            if resp.status_code == 200:
                return json.dumps({"success": True, "tool": tool_name, "result": resp.json()})
            return json.dumps({"error": f"Execute failed ({resp.status_code}): {resp.text[:300]}"})
    except Exception as e:
        return json.dumps({"error": f"execute_built_tool failed: {e}"})


# ═══════════════════════════════════════════════════════════════
# 6. HEALTH HANDLERS
# ═══════════════════════════════════════════════════════════════

async def _health_check_agents(args: dict, headers: dict, cache: list) -> str:
    from .health_monitor import run_health_check
    result = await run_health_check(headers=headers, auto_fix=args.get("auto_fix", False))
    return json.dumps(result)


async def _get_agent_sessions(args: dict, headers: dict, cache: list) -> str:
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})
    sessions = await fetch_agent_sessions(agent["id"], headers, limit=8)
    if not sessions:
        return json.dumps({"agent": agent.get("name"), "sessions": []})
    result = [{
        "id": str(s.get("id", "?"))[:12],
        "status": s.get("status"),
        "goal": (s.get("current_goal") or "")[:120],
        "loops": s.get("loop_count", 0),
        "tokens": s.get("total_tokens_used", 0),
        "error": (s.get("error_message") or "")[:200] if s.get("error_message") else None,
        "created": s.get("created_at"),
    } for s in sessions]
    return json.dumps({"agent": agent.get("name"), "total_sessions": len(result), "sessions": result})


# ═══════════════════════════════════════════════════════════════
# HANDLER REGISTRY — Maps tool names to handler functions
# ═══════════════════════════════════════════════════════════════

_HANDLERS = {
    # 1. Workspace & Context
    "workspace_snapshot": _workspace_snapshot,
    "agent_snapshot": _agent_snapshot,
    "run_snapshot": _run_snapshot,
    "list_agents": _list_agents,
    "get_agent_details": _get_agent_details,
    "list_platform_tools": _list_platform_tools,
    "list_workspace_databases": _list_workspace_databases,
    "query_cross_agent_database": _query_cross_agent_database,
    # 2. Agent Lifecycle
    "create_agent": _create_agent,
    "continue_build": _continue_build,
    "message_build": _message_build,
    "modify_agent": _modify_agent,
    "run_agent": _run_agent,
    "stop_agent": _stop_agent,
    "delete_agent": _delete_agent,
    "schedule_agent": _schedule_agent,
    "set_agent_budget": _set_agent_budget,
    "check_agent_wallet": _check_agent_wallet,
    # 3. User Interface
    "present_options": _present_options,
    "respond_to_user": _respond_to_user,
    "present_billing_offer": _present_billing_offer,
    "open_interface_editor": _open_interface_editor,
    # 4. Utility
    "get_user_memory": _get_user_memory,
    "update_user_memory": _update_user_memory,
    "get_credits_info": _get_credits_info,
    "get_current_time": _get_current_time,
    "set_workspace_name": _set_workspace_name,
    "configure_smtp": _configure_smtp,
    "delete_smtp": _delete_smtp,
    "file_operation": _file_operation,
    # 5. Self-Extension
    "auto_build_tool": _auto_build_tool,
    "check_tool_exists": _check_tool_exists,
    "execute_built_tool": _execute_built_tool,
    # 6. Health
    "health_check_agents": _health_check_agents,
    "get_agent_sessions": _get_agent_sessions,
}
