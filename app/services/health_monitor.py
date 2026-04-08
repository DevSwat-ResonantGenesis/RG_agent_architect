"""
RG Agent Architect — Health Monitor

Proactive agent health checks and post-run diagnostics.
Twin architecture: after every run, check for patterns of failure
and auto-fix when safe (Twin proactive_defaults).
"""
import json
import logging

import httpx

from ..config import settings
from .runner import fetch_agent_sessions

logger = logging.getLogger(__name__)

AGENT_ENGINE_URL = settings.AGENT_ENGINE_URL


async def run_health_check(headers: dict, auto_fix: bool = False) -> dict:
    """Scan all agents for health issues.

    Detects:
    - Consecutive failures (2+)
    - Stuck sessions (loop_count > 80)
    - Common error patterns → recommended fixes

    Returns: {agents_checked, issues_found, issues, fixes_applied}
    """
    # Fetch agents
    agents = []
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
            r = await c.get(f"{AGENT_ENGINE_URL}/agents/", headers=headers)
            if r.status_code == 200:
                data = r.json()
                agents = data if isinstance(data, list) else data.get("agents", [])
    except Exception as e:
        logger.warning(f"[HEALTH] Agent fetch failed: {e}")
        return {"agents_checked": 0, "issues_found": 0, "issues": [], "error": str(e)}

    if not agents:
        return {"agents_checked": 0, "issues_found": 0, "issues": [], "message": "No agents to check."}

    issues: list[dict] = []
    fixes_applied: list[dict] = []

    for agent in agents[:20]:
        agent_id = agent.get("id")
        name = agent.get("name", "?")
        if not agent_id:
            continue

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
            if "Maximum loop iterations" in last_error:
                fix_action = {"change": "max_loops", "from": 25, "to": 50}
            elif "timeout" in last_error.lower():
                fix_action = {"change": "timeout_seconds", "from": 300, "to": 600}
            elif "rate_limit" in last_error.lower() or "429" in last_error:
                fix_action = {"change": "model", "to": "llama-3.3-70b-versatile"}

            if fix_action:
                issue["recommended_fix"] = fix_action

                if auto_fix:
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

        # Check: stuck sessions
        for s in sessions[:1]:
            if s.get("status") == "running" and s.get("loop_count", 0) > 80:
                issues.append({
                    "agent": name,
                    "agent_id": agent_id,
                    "issue": "stuck_session",
                    "loops": s.get("loop_count", 0),
                    "session_id": str(s.get("id", "?"))[:12],
                    "recommended_fix": {"action": "stop_and_restart"},
                })

    return {
        "agents_checked": len(agents),
        "issues_found": len(issues),
        "issues": issues,
        "fixes_applied": fixes_applied,
    }


async def check_agent_after_run(
    agent_id: str, session_status: str, headers: dict
) -> bool:
    """Lightweight post-run check. Called by /run-complete webhook.

    If the run failed, check if it's a pattern and auto-fix.
    Returns True if a fix was applied.
    """
    if session_status not in ("failed", "error"):
        return False

    sessions = await fetch_agent_sessions(agent_id, headers, limit=3)
    if not sessions:
        return False

    consecutive_fails = sum(1 for s in sessions if s.get("status") == "failed")
    if consecutive_fails < 2:
        return False

    last_error = (sessions[0].get("error_message") or "")[:200]

    # Auto-fix: increase max_loops if that's the issue
    if "Maximum loop iterations" in last_error:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
                resp = await c.patch(
                    f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                    headers={**headers, "Content-Type": "application/json"},
                    json={"safety_config": {"max_loops": 50}},
                )
                if resp.status_code in (200, 204):
                    logger.info(f"[HEALTH] Auto-fixed max_loops for agent {agent_id}")
                    return True
        except Exception as e:
            logger.warning(f"[HEALTH] Auto-fix failed: {e}")

    return False
