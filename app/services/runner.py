"""
RG Agent Architect — Agent Runner

Handles agent execution via Agent Engine API:
- run_agent_full: Start agent → poll for completion → return results
- fetch_agent_sessions: Get recent execution history
- create_schedule: Set up recurring triggers (Twin set_trigger)
- parse_schedule_from_message: Extract schedule intent from user text

Twin architecture (twin.md lines 357-360):
Runner = smaller, cheaper model that follows instructions.
Builder = high-reasoning model that creates/updates agents.
"""
import asyncio
import json
import logging
import re

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

AGENT_ENGINE_URL = settings.AGENT_ENGINE_URL


async def run_agent_full(
    agent_id: str,
    agent_name: str,
    task: str,
    headers: dict,
) -> dict:
    """Start an agent run and poll until completion or timeout.

    Returns:
        {"status": "completed"|"failed"|"timeout", "output": ..., "steps": ..., "error": ...}
    """
    # Step 1: Start the run
    session_id = await _start_run(agent_id, task, headers)
    if not session_id:
        return {"status": "failed", "error": "Could not start agent run"}

    logger.info(f"[RUNNER] Started run for '{agent_name}' (session={session_id[:12]})")

    # Step 2: Poll for completion
    poll_interval = settings.POLL_INTERVAL
    max_rounds = settings.POLL_MAX_ROUNDS

    for i in range(max_rounds):
        await asyncio.sleep(poll_interval)
        result = await _check_run_status(session_id, headers)

        if not result:
            continue

        status = result.get("status", "").lower()

        if status in ("completed", "success"):
            return {
                "status": "completed",
                "output": result.get("output") or result.get("final_output") or result.get("summary", ""),
                "steps": result.get("loop_count", 0),
                "session_id": session_id,
            }

        if status in ("failed", "error"):
            return {
                "status": "failed",
                "error": result.get("error_message") or result.get("error", "Unknown error"),
                "output": result.get("output", ""),
                "steps": result.get("loop_count", 0),
                "session_id": session_id,
            }

        if status in ("stopped", "cancelled"):
            return {
                "status": "stopped",
                "output": result.get("output", ""),
                "steps": result.get("loop_count", 0),
                "session_id": session_id,
            }

        # Still running — log progress
        loops = result.get("loop_count", 0)
        if i % 4 == 0:
            logger.info(f"[RUNNER] '{agent_name}' still running (loop {loops}, poll {i+1}/{max_rounds})")

    return {
        "status": "timeout",
        "error": f"Agent still running after {max_rounds * poll_interval}s. Check back with get_agent_sessions.",
        "session_id": session_id,
    }


async def _start_run(agent_id: str, task: str, headers: dict) -> str:
    """Start an agent execution, return session_id."""
    # Try multiple endpoint patterns
    endpoints = [
        (f"{AGENT_ENGINE_URL}/execution/start", {"agent_id": agent_id, "goal": task}),
        (f"{AGENT_ENGINE_URL}/agents/{agent_id}/run", {"task": task}),
        (f"{AGENT_ENGINE_URL}/agents/{agent_id}/execute", {"goal": task}),
    ]

    for url, payload in endpoints:
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
                resp = await c.post(
                    url,
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code in (200, 201, 202):
                    data = resp.json()
                    sid = data.get("session_id") or data.get("id") or data.get("execution_id", "")
                    if sid:
                        return str(sid)
        except Exception as e:
            logger.debug(f"[RUNNER] Endpoint {url} failed: {e}")
            continue

    logger.error(f"[RUNNER] All start endpoints failed for agent {agent_id}")
    return ""


async def _check_run_status(session_id: str, headers: dict) -> dict:
    """Poll the execution status of a session."""
    endpoints = [
        f"{AGENT_ENGINE_URL}/execution/session/{session_id}",
        f"{AGENT_ENGINE_URL}/execution/status/{session_id}",
    ]

    for url in endpoints:
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
                resp = await c.get(url, headers=headers)
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            continue

    return {}


async def fetch_agent_sessions(
    agent_id: str, headers: dict, limit: int = 5
) -> list[dict]:
    """Fetch recent execution sessions for an agent."""
    endpoints = [
        f"{AGENT_ENGINE_URL}/execution/history/{agent_id}",
        f"{AGENT_ENGINE_URL}/agents/{agent_id}/sessions",
    ]

    for url in endpoints:
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
                resp = await c.get(url, headers=headers, params={"limit": limit})
                if resp.status_code == 200:
                    data = resp.json()
                    return data if isinstance(data, list) else data.get("sessions", [])
        except Exception:
            continue

    return []


async def create_schedule(
    agent_id: str,
    agent_name: str,
    interval_seconds: int,
    cron_expression: str | None,
    goal: str,
    headers: dict,
) -> bool:
    """Create a recurring schedule (Twin set_trigger)."""
    payload: dict = {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "goal": goal,
        "is_active": True,
    }

    if cron_expression:
        payload["cron_expression"] = cron_expression
    else:
        payload["interval_seconds"] = interval_seconds

    endpoints = [
        f"{AGENT_ENGINE_URL}/schedules/",
        f"{AGENT_ENGINE_URL}/agents/{agent_id}/schedule",
    ]

    for url in endpoints:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
                resp = await c.post(
                    url,
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    logger.info(f"[RUNNER] Schedule created for '{agent_name}'")
                    return True
        except Exception:
            continue

    logger.warning(f"[RUNNER] Schedule creation failed for '{agent_name}'")
    return False


def parse_schedule_from_message(message: str) -> dict:
    """Extract schedule intent from user message text.

    Returns {"interval_seconds": int, "cron": str|None, "description": str}
    """
    msg = message.lower()

    patterns = [
        (r"every\s+(\d+)\s+minute", lambda m: int(m.group(1)) * 60),
        (r"every\s+(\d+)\s+hour", lambda m: int(m.group(1)) * 3600),
        (r"every\s+(\d+)\s+day", lambda m: int(m.group(1)) * 86400),
        (r"every\s+minute", lambda _: 60),
        (r"every\s+hour|hourly", lambda _: 3600),
        (r"every\s+day|daily", lambda _: 86400),
        (r"every\s+week|weekly", lambda _: 604800),
        (r"twice\s+a\s+day", lambda _: 43200),
        (r"every\s+morning", lambda _: 86400),
        (r"every\s+night", lambda _: 86400),
    ]

    for pattern, extractor in patterns:
        match = re.search(pattern, msg)
        if match:
            seconds = extractor(match)
            labels = {60: "every minute", 3600: "hourly", 43200: "twice daily",
                      86400: "daily", 604800: "weekly"}
            desc = labels.get(seconds, f"every {seconds}s")
            return {"interval_seconds": seconds, "cron": None, "description": desc}

    return {"interval_seconds": 86400, "cron": None, "description": "daily (default)"}
