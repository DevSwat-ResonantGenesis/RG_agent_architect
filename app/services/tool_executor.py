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
        elif tool_name == "set_agent_budget":
            return await _set_agent_budget(arguments, headers, agents_cache)
        elif tool_name == "check_agent_wallet":
            return await _check_agent_wallet(arguments, headers, agents_cache)
        elif tool_name == "auto_build_tool":
            return await _auto_build_tool(arguments, headers)
        elif tool_name == "check_tool_exists":
            return await _check_tool_exists(arguments, headers)
        elif tool_name == "execute_built_tool":
            return await _execute_built_tool(arguments, headers)
        elif tool_name == "health_check_agents":
            return await _health_check_agents(arguments, headers, agents_cache)
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
    budget = args.get("budget") or {}
    max_loops = args.get("max_loops", 30)  # Default 30, not 25

    # System prompt is CRITICAL — it's the agent's step-by-step instructions
    system_prompt = args.get("system_prompt")
    if not system_prompt or len(system_prompt) < 50:
        # Generate a reasonable fallback if Architect didn't provide detailed instructions
        name = args.get("name", "Agent")
        goal = args.get("goal", "")
        tools = args.get("tools", [])
        system_prompt = (
            f"You are {name}, an autonomous agent.\n\n"
            f"YOUR GOAL: {goal}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Use your available tools ({', '.join(tools)}) to accomplish the goal above.\n"
            f"2. Break the task into clear steps and execute them one by one.\n"
            f"3. After collecting results, compile them into a structured format.\n"
            f"4. Store your final results using Memory Store so they are saved.\n"
            f"5. Do NOT hallucinate data — only report what your tools actually returned.\n"
            f"6. Include source URLs for any web-sourced information.\n"
        )
        logger.warning(f"[TOOL] create_agent: system_prompt was missing/short, generated fallback for '{name}'")

    payload = {
        "name": args.get("name", "New Agent"),
        "description": args.get("description", ""),
        "system_prompt": system_prompt,
        "goal": args.get("goal", ""),
        "provider": args.get("provider", "groq"),
        "model": args.get("model", "llama-3.3-70b-versatile"),
        "tools": args.get("tools", []),
        "temperature": args.get("temperature", 0.6),
        "max_tokens": args.get("max_tokens", 4096),
        "mode": args.get("mode", "governed"),
        "is_active": True,
    }

    # Pass max_loops via safety_config
    safety_config = {"max_loops": max_loops}
    payload["safety_config"] = safety_config

    if budget:
        payload["budget_config"] = {
            "max_tokens_per_run": budget.get("max_tokens_per_run", 50000),
            "max_runs_per_day": budget.get("max_runs_per_day", 10),
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
                agent_id = data.get("id")
                result_info = {
                    "success": True,
                    "id": agent_id,
                    "name": data.get("name"),
                    "model": data.get("model"),
                    "tools": data.get("tools", []),
                }
                # Create wallet with initial credits if budget specified
                if agent_id and budget.get("initial_credits"):
                    wallet_ok = await _create_agent_wallet(
                        agent_id, budget["initial_credits"], headers
                    )
                    result_info["wallet_created"] = wallet_ok
                    result_info["initial_credits"] = budget.get("initial_credits")
                return json.dumps(result_info)
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


# ═══════════════════════════════════════════════════════════════
# BUDGET & WALLET TOOLS
# ═══════════════════════════════════════════════════════════════

async def _create_agent_wallet(
    agent_id: str, initial_credits: float, headers: dict
) -> bool:
    """Create a wallet for an agent with initial credit allocation."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.post(
                f"{AGENT_ENGINE_URL}/wallets/agent/{agent_id}",
                headers={**headers, "Content-Type": "application/json"},
                json={"initial_balance": initial_credits, "currency": "credits"},
            )
            if resp.status_code in (200, 201):
                logger.info(f"[TOOL] Wallet created for {agent_id} with {initial_credits} credits")
                return True
            # Fallback: try credit deposit endpoint
            resp2 = await c.post(
                f"{AGENT_ENGINE_URL}/credits/deposit",
                headers={**headers, "Content-Type": "application/json"},
                json={"agent_id": agent_id, "amount": initial_credits, "reason": "Initial allocation by Architect"},
            )
            return resp2.status_code in (200, 201)
    except Exception as e:
        logger.warning(f"[TOOL] Wallet creation failed for {agent_id}: {e}")
        return False


async def _set_agent_budget(args: dict, headers: dict, agents_cache: list[dict]) -> str:
    """Set budget limits for an agent."""
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, agents_cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})

    agent_id = agent["id"]
    name = agent.get("name", agent_name)
    changes: dict = {}

    max_tokens = args.get("max_tokens_per_run")
    max_runs = args.get("max_runs_per_day")
    credits_amount = args.get("credits")

    if max_tokens or max_runs:
        budget_config = {}
        if max_tokens:
            budget_config["max_tokens_per_run"] = max_tokens
        if max_runs:
            budget_config["max_runs_per_day"] = max_runs
        changes["budget_config"] = budget_config

    # Apply config changes via PATCH
    result: dict = {"agent": name}
    if changes:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
                resp = await c.patch(
                    f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                    headers={**headers, "Content-Type": "application/json"},
                    json=changes,
                )
                result["budget_updated"] = resp.status_code in (200, 204)
                result["budget_config"] = changes.get("budget_config")
        except Exception as e:
            result["budget_error"] = str(e)

    # Deposit credits if requested
    if credits_amount:
        wallet_ok = await _create_agent_wallet(agent_id, credits_amount, headers)
        result["credits_deposited"] = wallet_ok
        result["credits_amount"] = credits_amount

    return json.dumps(result)


async def _check_agent_wallet(args: dict, headers: dict, agents_cache: list[dict]) -> str:
    """Check an agent's wallet balance and recent transactions."""
    agent_name = args.get("agent_name", "")
    agent = _find_agent(agent_name, agents_cache)
    if not agent:
        return json.dumps({"error": f"Agent '{agent_name}' not found."})

    agent_id = agent["id"]
    name = agent.get("name", agent_name)

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            # Try wallet endpoint
            resp = await c.get(
                f"{AGENT_ENGINE_URL}/wallets/agent/{agent_id}",
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                return json.dumps({
                    "agent": name,
                    "balance": data.get("balance", 0),
                    "currency": data.get("currency", "credits"),
                    "total_spent": data.get("total_spent", 0),
                    "transactions": data.get("recent_transactions", [])[:5],
                })

            # Fallback: try credits endpoint
            resp2 = await c.get(
                f"{AGENT_ENGINE_URL}/credits/agent/{agent_id}",
                headers=headers,
            )
            if resp2.status_code == 200:
                data = resp2.json()
                return json.dumps({"agent": name, **data})

            return json.dumps({"agent": name, "wallet": "not_found", "message": "No wallet exists for this agent yet. Use set_agent_budget to create one."})
    except Exception as e:
        return json.dumps({"error": f"Wallet check failed: {e}"})


# ═══════════════════════════════════════════════════════════════
# SELF-EXTENSION TOOLS (auto_build_tool, check_tool_exists, execute_built_tool)
# ═══════════════════════════════════════════════════════════════

async def _auto_build_tool(args: dict, headers: dict) -> str:
    """Create a new tool dynamically via Agent Engine's tool builder."""
    tool_name = args.get("tool_name", "")
    description = args.get("description", "")
    input_schema = args.get("input_schema", {})
    hint = args.get("implementation_hint", "")

    if not tool_name or not description:
        return json.dumps({"error": "tool_name and description are required."})

    payload = {
        "name": tool_name,
        "description": description,
        "input_schema": input_schema,
        "implementation_hint": hint,
        "source": "agent_architect",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as c:
            resp = await c.post(
                f"{AGENT_ENGINE_URL}/agents/tools/execute",
                headers={**headers, "Content-Type": "application/json"},
                json={"tool_name": "auto_build_tool", "tool_input": payload},
            )
            print(f"[TOOL_EXEC] auto_build_tool → {resp.status_code}", flush=True)
            if resp.status_code in (200, 201):
                data = resp.json()
                return json.dumps({
                    "success": True,
                    "tool_name": tool_name,
                    "message": f"Tool '{tool_name}' created and registered.",
                    "details": data,
                })
            else:
                return json.dumps({"error": f"auto_build_tool failed ({resp.status_code}): {resp.text[:300]}"})
    except Exception as e:
        return json.dumps({"error": f"auto_build_tool failed: {e}"})


async def _check_tool_exists(args: dict, headers: dict) -> str:
    """Check if a tool exists on the platform."""
    tool_name = args.get("tool_name", "")
    if not tool_name:
        return json.dumps({"error": "tool_name is required."})

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.post(
                f"{AGENT_ENGINE_URL}/agents/tools/execute",
                headers={**headers, "Content-Type": "application/json"},
                json={"tool_name": "check_tool_exists", "tool_input": {"tool_name": tool_name}},
            )
            if resp.status_code == 200:
                data = resp.json()
                return json.dumps(data)
            # Fallback: search tools list
            resp2 = await c.get(f"{AGENT_ENGINE_URL}/agents/tools/list", headers=headers)
            if resp2.status_code == 200:
                tools = resp2.json()
                tool_list = tools if isinstance(tools, list) else tools.get("tools", [])
                found = any(
                    (t.get("name", "") if isinstance(t, dict) else str(t)) == tool_name
                    for t in tool_list
                )
                return json.dumps({"tool_name": tool_name, "exists": found})
    except Exception as e:
        return json.dumps({"error": f"check_tool_exists failed: {e}"})

    return json.dumps({"tool_name": tool_name, "exists": False, "message": "Could not verify. Try auto_build_tool to create it."})


async def _execute_built_tool(args: dict, headers: dict) -> str:
    """Execute a dynamically-built tool."""
    tool_name = args.get("tool_name", "")
    inputs = args.get("inputs", {})
    if not tool_name:
        return json.dumps({"error": "tool_name is required."})

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as c:
            resp = await c.post(
                f"{AGENT_ENGINE_URL}/agents/tools/execute",
                headers={**headers, "Content-Type": "application/json"},
                json={"tool_name": tool_name, "tool_input": inputs},
            )
            if resp.status_code == 200:
                return json.dumps({"success": True, "tool": tool_name, "result": resp.json()})
            return json.dumps({"error": f"Execute failed ({resp.status_code}): {resp.text[:300]}"})
    except Exception as e:
        return json.dumps({"error": f"execute_built_tool failed: {e}"})


# ═══════════════════════════════════════════════════════════════
# HEALTH CHECK & PROACTIVE FAILURE RECOVERY
# ═══════════════════════════════════════════════════════════════

async def _health_check_agents(
    args: dict, headers: dict, agents_cache: list[dict]
) -> str:
    """Scan all agents for health issues and optionally auto-fix."""
    auto_fix = args.get("auto_fix", False)

    # Refresh agent list
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
        return json.dumps({"message": "No agents to check.", "issues": []})

    issues: list[dict] = []
    fixes_applied: list[dict] = []

    for agent in agents[:20]:
        agent_id = agent.get("id")
        name = agent.get("name", "?")
        if not agent_id:
            continue

        # Fetch recent sessions
        sessions = await fetch_agent_sessions(agent_id, headers, limit=5)
        if not sessions:
            continue

        # Check: consecutive failures
        consecutive_fails = 0
        last_error = ""
        for s in sessions:
            if s.get("status") == "failed":
                consecutive_fails += 1
                if not last_error:
                    last_error = (s.get("error_message") or "")[:200]
            else:
                break

        if consecutive_fails >= 2:
            issue = {
                "agent": name,
                "agent_id": agent_id,
                "issue": "consecutive_failures",
                "count": consecutive_fails,
                "last_error": last_error,
            }

            # Determine fix
            fix_action = None
            if "Maximum loop iterations reached" in last_error:
                fix_action = {"change": "max_loops", "from": 25, "to": 50}
            elif "timeout" in last_error.lower():
                fix_action = {"change": "timeout_seconds", "from": 300, "to": 600}
            elif "rate_limit" in last_error.lower() or "429" in last_error:
                fix_action = {"change": "model", "to": "llama-3.3-70b-versatile", "reason": "rate limit — switch provider"}

            if fix_action:
                issue["recommended_fix"] = fix_action

                if auto_fix and fix_action.get("change"):
                    changes = {}
                    if fix_action["change"] == "max_loops":
                        changes = {"safety_config": {"max_loops": fix_action["to"]}}
                    elif fix_action["change"] == "timeout_seconds":
                        changes = {"safety_config": {"timeout_seconds": fix_action["to"]}}
                    elif fix_action["change"] == "model":
                        changes = {"model": fix_action["to"]}

                    if changes:
                        try:
                            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
                                resp = await c.patch(
                                    f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                                    headers={**headers, "Content-Type": "application/json"},
                                    json=changes,
                                )
                                if resp.status_code in (200, 204):
                                    fixes_applied.append({"agent": name, "fix": fix_action})
                                    issue["auto_fixed"] = True
                        except Exception as e:
                            issue["fix_error"] = str(e)

            issues.append(issue)

        # Check: stuck sessions (running for too long)
        for s in sessions[:1]:
            if s.get("status") == "running":
                loop_count = s.get("loop_count", 0)
                if loop_count > 80:
                    issues.append({
                        "agent": name,
                        "agent_id": agent_id,
                        "issue": "stuck_session",
                        "loops": loop_count,
                        "session_id": str(s.get("id", "?"))[:12],
                        "recommended_fix": {"action": "stop_and_restart"},
                    })

    return json.dumps({
        "agents_checked": len(agents),
        "issues_found": len(issues),
        "issues": issues,
        "fixes_applied": fixes_applied,
    })


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
