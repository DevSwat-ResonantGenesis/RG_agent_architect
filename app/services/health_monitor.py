"""
RG Agent Architect — Proactive Health Monitor

Background service that periodically checks all agents for health issues
and auto-fixes common problems without user interaction.

Detects:
- Consecutive failures (2+) → auto-increase max_loops, swap model
- Stuck sessions (running with 80+ loops) → flag for restart
- Depleted wallets → flag for top-up
- Inactive agents with schedules → flag as misconfigured

Can be triggered:
1. Via the health_check_agents tool in the ReAct loop
2. Via POST /health-check endpoint
3. Automatically after each agent run completion (webhook)
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

AGENT_ENGINE_URL = settings.AGENT_ENGINE_URL

# Thresholds
CONSECUTIVE_FAIL_THRESHOLD = 2
STUCK_LOOP_THRESHOLD = 80
MAX_LOOPS_INCREASE_TO = 50
TIMEOUT_INCREASE_TO = 600


async def run_health_check(
    headers: dict[str, str],
    auto_fix: bool = False,
) -> dict:
    """Full health scan across all user agents.

    Returns:
        dict with agents_checked, issues_found, issues[], fixes_applied[]
    """
    logger.info("[HEALTH] Starting proactive health check")

    # Fetch all agents
    agents = []
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            r = await c.get(f"{AGENT_ENGINE_URL}/agents/", headers=headers)
            if r.status_code == 200:
                data = r.json()
                agents = data if isinstance(data, list) else data.get("agents", [])
    except Exception as e:
        logger.warning(f"[HEALTH] Failed to fetch agents: {e}")
        return {"error": str(e), "agents_checked": 0, "issues": []}

    if not agents:
        return {"agents_checked": 0, "issues_found": 0, "issues": [], "fixes_applied": []}

    issues: list[dict] = []
    fixes_applied: list[dict] = []

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for agent in agents[:25]:
            agent_id = agent.get("id")
            name = agent.get("name", "?")
            if not agent_id:
                continue

            agent_issues = await _check_single_agent(
                client, agent_id, name, agent, headers, auto_fix
            )
            for issue in agent_issues:
                issues.append(issue)
                if issue.get("auto_fixed"):
                    fixes_applied.append({"agent": name, "fix": issue.get("recommended_fix")})

    result = {
        "agents_checked": len(agents),
        "issues_found": len(issues),
        "issues": issues,
        "fixes_applied": fixes_applied,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if issues:
        logger.warning(f"[HEALTH] Found {len(issues)} issues across {len(agents)} agents")
    else:
        logger.info(f"[HEALTH] All {len(agents)} agents healthy")

    return result


async def _check_single_agent(
    client: httpx.AsyncClient,
    agent_id: str,
    name: str,
    agent: dict,
    headers: dict[str, str],
    auto_fix: bool,
) -> list[dict]:
    """Check a single agent for health issues."""
    issues: list[dict] = []

    # Fetch recent sessions
    sessions = []
    try:
        r = await client.get(
            f"{AGENT_ENGINE_URL}/agents/{agent_id}/sessions",
            headers=headers,
            params={"limit": 5},
        )
        if r.status_code == 200:
            data = r.json()
            sessions = data if isinstance(data, list) else []
    except Exception:
        return issues

    if not sessions:
        return issues

    # === Check 1: Consecutive failures ===
    consecutive_fails = 0
    last_error = ""
    for s in sessions:
        if s.get("status") == "failed":
            consecutive_fails += 1
            if not last_error:
                last_error = (s.get("error_message") or "")[:200]
        else:
            break

    if consecutive_fails >= CONSECUTIVE_FAIL_THRESHOLD:
        issue = {
            "agent": name,
            "agent_id": agent_id,
            "issue": "consecutive_failures",
            "count": consecutive_fails,
            "last_error": last_error,
        }

        # Determine recommended fix based on error
        fix = _determine_fix(last_error, agent)
        if fix:
            issue["recommended_fix"] = fix
            if auto_fix:
                applied = await _apply_fix(client, agent_id, fix, headers)
                issue["auto_fixed"] = applied

        issues.append(issue)

    # === Check 2: Stuck sessions ===
    latest = sessions[0] if sessions else {}
    if latest.get("status") == "running":
        loop_count = latest.get("loop_count", 0)
        if loop_count > STUCK_LOOP_THRESHOLD:
            issues.append({
                "agent": name,
                "agent_id": agent_id,
                "issue": "stuck_session",
                "loops": loop_count,
                "session_id": str(latest.get("id", "?"))[:12],
                "recommended_fix": {"action": "investigate", "reason": f"Running with {loop_count} loops"},
            })

    # === Check 3: Inactive agent with schedule ===
    if not agent.get("is_active", True):
        # Check if it has schedules
        try:
            r = await client.get(
                f"{AGENT_ENGINE_URL}/agents/{agent_id}/schedules",
                headers=headers,
            )
            if r.status_code == 200:
                scheds = r.json()
                if isinstance(scheds, list) and scheds:
                    issues.append({
                        "agent": name,
                        "agent_id": agent_id,
                        "issue": "inactive_with_schedule",
                        "schedules": len(scheds),
                        "recommended_fix": {"action": "activate", "reason": "Agent has schedules but is inactive"},
                    })
                    if auto_fix:
                        try:
                            resp = await client.patch(
                                f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                                headers={**headers, "Content-Type": "application/json"},
                                json={"is_active": True},
                            )
                            if resp.status_code in (200, 204):
                                issues[-1]["auto_fixed"] = True
                        except Exception:
                            pass
        except Exception:
            pass

    return issues


def _determine_fix(error: str, agent: dict) -> dict | None:
    """Analyze error message and recommend a fix."""
    error_lower = error.lower()

    if "maximum loop iterations reached" in error_lower:
        current = agent.get("safety_config", {}).get("max_loops", 25) if isinstance(agent.get("safety_config"), dict) else 25
        return {
            "change": "max_loops",
            "from": current,
            "to": min(current * 2, 100),
            "reason": "Agent needs more iterations to complete task",
        }

    if "timeout" in error_lower or "timed out" in error_lower:
        return {
            "change": "timeout_seconds",
            "from": 300,
            "to": TIMEOUT_INCREASE_TO,
            "reason": "Agent timing out — increasing timeout",
        }

    if "rate_limit" in error_lower or "429" in error or "too many requests" in error_lower:
        current_model = agent.get("model", "")
        if "gpt" in current_model:
            return {
                "change": "model",
                "to": "llama-3.3-70b-versatile",
                "provider": "groq",
                "reason": "Rate limited on OpenAI — switching to Groq",
            }
        return {
            "change": "model",
            "to": "llama-3.1-8b-instant",
            "provider": "groq",
            "reason": "Rate limited — switching to faster model",
        }

    if "insufficient" in error_lower and "credit" in error_lower:
        return {
            "change": "credits",
            "action": "top_up",
            "reason": "Agent ran out of credits",
        }

    return None


async def _apply_fix(
    client: httpx.AsyncClient,
    agent_id: str,
    fix: dict,
    headers: dict[str, str],
) -> bool:
    """Apply a recommended fix to an agent."""
    change_type = fix.get("change", "")
    changes: dict = {}

    if change_type == "max_loops":
        changes = {"safety_config": {"max_loops": fix["to"]}}
    elif change_type == "timeout_seconds":
        changes = {"safety_config": {"timeout_seconds": fix["to"]}}
    elif change_type == "model":
        changes = {"model": fix["to"]}
        if fix.get("provider"):
            changes["provider"] = fix["provider"]
    else:
        return False

    try:
        resp = await client.patch(
            f"{AGENT_ENGINE_URL}/agents/{agent_id}",
            headers={**headers, "Content-Type": "application/json"},
            json=changes,
        )
        applied = resp.status_code in (200, 204)
        if applied:
            logger.info(f"[HEALTH] Auto-fixed {agent_id}: {fix}")
        return applied
    except Exception as e:
        logger.warning(f"[HEALTH] Auto-fix failed for {agent_id}: {e}")
        return False


async def check_agent_after_run(
    agent_id: str,
    session_status: str,
    headers: dict[str, str],
) -> dict | None:
    """Lightweight post-run check. Called after each agent execution completes.

    If the session failed, checks if this is part of a pattern and auto-fixes.
    Returns fix info if a fix was applied, None otherwise.
    """
    if session_status != "failed":
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            # Get agent info
            r = await c.get(f"{AGENT_ENGINE_URL}/agents/{agent_id}", headers=headers)
            if r.status_code != 200:
                return None
            agent = r.json()

            # Check for consecutive failures
            issues = await _check_single_agent(
                c, agent_id, agent.get("name", "?"), agent, headers, auto_fix=True
            )

            applied_fixes = [i for i in issues if i.get("auto_fixed")]
            if applied_fixes:
                logger.info(f"[HEALTH] Post-run auto-fix for {agent_id}: {applied_fixes}")
                return {"agent_id": agent_id, "fixes": applied_fixes}
    except Exception as e:
        logger.debug(f"[HEALTH] Post-run check failed: {e}")

    return None
