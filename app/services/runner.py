"""
RG Agent Architect — Runner Service
Agent execution, polling for results, scheduling.
"""
import asyncio
import logging
import re

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# AGENT EXECUTION
# ═══════════════════════════════════════════════════════════════

async def activate_agent(
    agent_id: str,
    headers: dict[str, str],
) -> bool:
    """Activate an agent (set is_active=True)."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.patch(
                f"{settings.AGENT_ENGINE_URL}/agents/{agent_id}",
                headers={**headers, "Content-Type": "application/json"},
                json={"is_active": True},
            )
            return resp.status_code == 200
    except Exception as e:
        logger.warning(f"[RUNNER] Activate failed for {agent_id}: {e}")
        return False


async def execute_agent(
    agent_id: str,
    task: str,
    headers: dict[str, str],
    context: dict | None = None,
) -> dict | None:
    """Start agent execution via Agent Engine. Returns exec data or None."""
    try:
        async with httpx.AsyncClient(timeout=settings.EXECUTION_TIMEOUT, follow_redirects=True) as c:
            resp = await c.post(
                f"{settings.AGENT_ENGINE_URL}/execution/agents/{agent_id}/execute",
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "task": task,
                    "context": context or {"source": "agent_architect"},
                },
            )
            if resp.status_code in (200, 201, 202):
                return resp.json()
            logger.warning(f"[RUNNER] Execute failed: HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[RUNNER] Execute error for {agent_id}: {e}")
    return None


async def poll_execution(
    agent_id: str,
    headers: dict[str, str],
    max_rounds: int | None = None,
    interval: float | None = None,
) -> dict:
    """Poll for execution results. Returns status dict."""
    rounds = max_rounds or settings.POLL_MAX_ROUNDS
    wait = interval or settings.POLL_INTERVAL

    result = {"status": "running", "output": None, "steps": 0, "error": None}

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
        for _ in range(rounds):
            await asyncio.sleep(wait)
            try:
                resp = await c.get(
                    f"{settings.AGENT_ENGINE_URL}/execution/history/{agent_id}",
                    headers=headers,
                    params={"limit": 1},
                )
                if resp.status_code == 200:
                    runs = resp.json()
                    if isinstance(runs, list) and runs:
                        latest = runs[0]
                        result["status"] = latest.get("status", "running")
                        result["output"] = latest.get("output") or latest.get("final_output")
                        result["steps"] = latest.get("loop_count") or latest.get("steps") or 0
                        result["error"] = latest.get("error") or latest.get("error_message")
                        result["session_id"] = latest.get("id") or latest.get("session_id")
                        if result["status"] in ("completed", "failed"):
                            break
            except Exception:
                break

    return result


async def run_agent_full(
    agent_id: str,
    agent_name: str,
    task: str,
    headers: dict[str, str],
) -> dict:
    """Full flow: activate → execute → poll. Returns execution result dict."""
    # Activate
    await activate_agent(agent_id, headers)

    # Execute
    exec_data = await execute_agent(agent_id, task, headers, {"source": "agent_architect", "first_run": True})
    if not exec_data:
        return {
            "agent_name": agent_name,
            "agent_id": agent_id,
            "status": "launch_failed",
            "error": "Execution request failed",
        }

    session_id = exec_data.get("session_id") or exec_data.get("id")
    logger.info(f"▶️ [RUNNER] Started {agent_name} ({agent_id}), session={session_id}")

    # Poll
    poll_result = await poll_execution(agent_id, headers)
    return {
        "agent_name": agent_name,
        "agent_id": agent_id,
        "session_id": session_id,
        **poll_result,
    }


async def run_agents_batch(
    agents: list[dict],
    blueprints: list[dict],
    headers: dict[str, str],
) -> list[dict]:
    """Execute multiple agents sequentially, polling each."""
    results = []
    for agent in agents:
        agent_id = agent.get("id")
        agent_name = agent.get("name", "Agent")
        if not agent_id:
            continue

        # Find matching blueprint for goal
        bp = next((b for b in blueprints if b.get("name") == agent_name), None)
        task = (bp or {}).get("goal") or agent.get("description") or f"Execute {agent_name}"

        result = await run_agent_full(agent_id, agent_name, task, headers)
        results.append(result)

    return results


# ═══════════════════════════════════════════════════════════════
# SCHEDULING
# ═══════════════════════════════════════════════════════════════

def parse_schedule_from_message(message: str) -> tuple[int, str | None, str]:
    """Parse schedule frequency from user message.

    Returns (interval_seconds, cron_expression, label)
    """
    msg = re.sub(r"^agent\s*architect\s*:\s*", "", message.lower().strip())

    if re.search(r"\b(hourly|every\s+hour)\b", msg):
        return 3600, None, "every hour"
    if re.search(r"\b(daily|every\s+day|every\s+morning|every\s+evening)\b", msg):
        return 86400, None, "daily"
    if re.search(r"\b(weekly|every\s+week)\b", msg):
        return 604800, None, "weekly"

    m = re.search(r"\bevery\s+(\d+)\s*(min|minute|hour|sec)", msg)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if "hour" in unit:
            return n * 3600, None, f"every {n} hours"
        elif "min" in unit:
            return n * 60, None, f"every {n} minutes"
        else:
            return n, None, f"every {n} seconds"

    # Default: every 6 hours
    return 21600, None, "every 6 hours"


async def create_schedule(
    agent_id: str,
    agent_name: str,
    interval_seconds: int,
    cron_expression: str | None,
    goal: str,
    headers: dict[str, str],
) -> bool:
    """Create a recurring schedule for an agent."""
    payload: dict = {
        "name": f"{agent_name} Schedule",
        "goal": goal,
    }
    if cron_expression:
        payload["cron_expression"] = cron_expression
    else:
        payload["interval_seconds"] = interval_seconds

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            resp = await c.post(
                f"{settings.AGENT_ENGINE_URL}/agents/{agent_id}/schedules",
                headers=headers,
                json=payload,
            )
            if resp.status_code in (200, 201):
                logger.info(f"⏰ [RUNNER] Schedule created for {agent_name}")
                return True
            logger.warning(f"[RUNNER] Schedule failed: HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[RUNNER] Schedule error: {e}")
    return False


# ═══════════════════════════════════════════════════════════════
# DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════

async def fetch_agent_sessions(
    agent_id: str,
    headers: dict[str, str],
    limit: int = 5,
) -> list[dict]:
    """Fetch recent sessions for an agent."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            resp = await c.get(
                f"{settings.AGENT_ENGINE_URL}/agents/{agent_id}/sessions",
                headers=headers,
                params={"limit": limit},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"[RUNNER] Sessions fetch failed: {e}")
    return []
