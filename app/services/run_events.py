"""
RG Agent Architect — Run Event Processing

Twin run_events state machine (twin.md lines 449-459):
- Receives build/run completion events from Agent Engine via webhook
- Classifies: build vs run × success/partial/fail/stopped/waiting
- Generates follow-up options per Twin's decision tree
- Forwards to chat service for real-time notification
- Stores for SSE polling

RULE: NEVER auto-trigger build/run/continue unless user explicitly asked.
"""
import json
import logging
from datetime import datetime, timezone

import httpx

from ..config import settings
from .models import RunEvent, RunEventType

logger = logging.getLogger(__name__)

# In-memory event queue per user (for SSE consumers)
_pending_events: dict[str, list[dict]] = {}


def classify_run_event(event_data: dict) -> RunEventType:
    """Classify incoming event per Twin's run_events taxonomy."""
    status = event_data.get("status", "").lower()
    is_build = event_data.get("is_build", False) or "build" in event_data.get("event_type", "").lower()

    if is_build:
        if status in ("completed", "success"):
            return RunEventType.BUILD_SUCCESS
        elif status == "partial":
            return RunEventType.BUILD_PARTIAL
        elif status in ("failed", "error"):
            return RunEventType.BUILD_FAIL
        elif status in ("stopped", "cancelled"):
            return RunEventType.BUILD_STOPPED
        elif status == "waiting_for_input":
            return RunEventType.WAITING_FOR_INPUT
        return RunEventType.BUILD_FAIL
    else:
        if status in ("completed", "success"):
            return RunEventType.RUN_SUCCESS
        elif status == "partial":
            return RunEventType.RUN_PARTIAL
        elif status in ("failed", "error"):
            return RunEventType.RUN_FAIL
        elif status in ("stopped", "cancelled"):
            return RunEventType.RUN_STOPPED
        elif status == "waiting_for_input":
            return RunEventType.WAITING_FOR_INPUT
        return RunEventType.RUN_FAIL


async def process_run_event(event_data: dict, headers: dict) -> dict:
    """Process an incoming run/build event.

    1. Classify event type
    2. Build RunEvent with follow-up options
    3. Store for SSE delivery
    4. Forward to chat service
    """
    agent_id = event_data.get("agent_id", "")
    agent_name = event_data.get("agent_name", "unknown")
    session_id = event_data.get("session_id", "")
    user_id = event_data.get("user_id", "") or headers.get("x-user-id", "")

    event_type = classify_run_event(event_data)

    run_event = RunEvent(
        agent_id=agent_id,
        agent_name=agent_name,
        event_type=event_type,
        session_id=session_id,
        summary=event_data.get("summary", ""),
        error=event_data.get("error", ""),
        output=str(event_data.get("output", ""))[:500],
        tool_calls=event_data.get("tool_calls", [])[:20],
        has_trigger=event_data.get("has_trigger", False),
    )

    follow_up = run_event.follow_up_options()
    message = _build_event_message(run_event)

    structured = {
        "type": "run_event",
        "event_type": event_type.value,
        "agent_name": agent_name,
        "agent_id": agent_id,
        "session_id": session_id,
        "message": message,
        "follow_up_options": follow_up,
        "timestamp": run_event.timestamp.isoformat(),
    }
    if run_event.error:
        structured["error"] = run_event.error
    if run_event.summary:
        structured["summary"] = run_event.summary

    # Queue for SSE consumers
    if user_id:
        _pending_events.setdefault(user_id, []).append(structured)
        _pending_events[user_id] = _pending_events[user_id][-50:]

    # Forward to chat service
    await _forward_to_chat(user_id, structured, headers)

    logger.info(f"[RUN_EVENT] {event_type.value} for '{agent_name}' (session={session_id[:12]})")
    return structured


def get_pending_events(user_id: str) -> list[dict]:
    """Get and clear pending events for a user."""
    return _pending_events.pop(user_id, [])


def _build_event_message(event: RunEvent) -> str:
    """Build human-readable message. Twin style: factual, no apologies."""
    name = event.agent_name

    msgs = {
        RunEventType.BUILD_SUCCESS: f"✅ **{name}** build completed successfully.",
        RunEventType.BUILD_PARTIAL: f"⚠️ **{name}** build partially completed.",
        RunEventType.BUILD_FAIL: f"❌ **{name}** build failed.",
        RunEventType.BUILD_STOPPED: f"⏹️ **{name}** build was stopped.",
        RunEventType.RUN_SUCCESS: f"✅ **{name}** run completed successfully.",
        RunEventType.RUN_PARTIAL: f"⚠️ **{name}** run partially completed.",
        RunEventType.RUN_FAIL: f"❌ **{name}** run failed.",
        RunEventType.RUN_STOPPED: f"⏹️ **{name}** run was stopped.",
        RunEventType.WAITING_FOR_INPUT: f"💬 **{name}** is waiting for your input.",
    }

    msg = msgs.get(event.event_type, f"Event for **{name}**: {event.event_type.value}")

    if event.error:
        msg += f"\n\nError: {event.error}"
    if event.summary:
        msg += f"\n\n{event.summary}"
    if event.output and event.event_type in (RunEventType.RUN_SUCCESS, RunEventType.RUN_PARTIAL):
        msg += f"\n\n**Output:**\n{event.output[:300]}"

    return msg


async def _forward_to_chat(user_id: str, event: dict, headers: dict) -> None:
    """Forward event to chat service for real-time notification."""
    chat_url = settings.CHAT_SERVICE_URL
    if not chat_url:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as c:
            await c.post(
                f"{chat_url}/chat/event",
                json={"user_id": user_id, "event": event, "source": "agent_architect"},
                headers=headers,
            )
    except Exception as e:
        logger.debug(f"[RUN_EVENT] Chat forward failed: {e}")
