"""
RG Agent Architect — Run Event Processing

Twin's Run Event State Machine (twin.md lines 1188-1253):
Receives build/run completion events from Agent Engine via webhook,
classifies them, generates follow-up options, and forwards to the
chat service for user notification.

RULE #1: NEVER auto-trigger build/run/continue unless user explicitly asked.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from ..config import settings
from .models import RunEvent, RunEventType

logger = logging.getLogger(__name__)

# In-memory store of recent events per user (for SSE consumers)
# Format: {user_id: [RunEvent, ...]}
_pending_events: dict[str, list[dict]] = {}


def classify_run_event(event_data: dict) -> RunEventType:
    """Classify an incoming event into Twin's event types.
    
    Twin's classification (twin.md Section 6):
    - First: is it a build event or run event?
    - Then: success / partial / fail / stopped / waiting
    """
    event_type = event_data.get("event_type", "")
    status = event_data.get("status", "").lower()
    is_build = event_data.get("is_build", False) or "build" in event_type.lower()

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
    """Process an incoming run/build event from Agent Engine.
    
    Twin's Run Event Processing (twin.md Section 6):
    1. Classify event type
    2. Build RunEvent with follow-up options
    3. Store for SSE delivery
    4. Forward to chat service if user is connected
    
    Returns structured event response with follow-up options.
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

    # Generate follow-up options per Twin's decision tree
    follow_up = run_event.follow_up_options()

    # Build the notification message
    message = _build_event_message(run_event)

    # Build structured event for SSE/chat
    structured_event = {
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
        structured_event["error"] = run_event.error
    if run_event.summary:
        structured_event["summary"] = run_event.summary

    # Store for SSE consumers
    if user_id:
        if user_id not in _pending_events:
            _pending_events[user_id] = []
        _pending_events[user_id].append(structured_event)
        # Keep max 50 events per user
        _pending_events[user_id] = _pending_events[user_id][-50:]

    # Forward to chat service for real-time notification
    await _forward_to_chat(user_id, structured_event, headers)

    logger.info(
        f"[RUN_EVENT] {event_type.value} for agent '{agent_name}' "
        f"(session={session_id[:12]}, user={user_id[:12]})"
    )

    return structured_event


def get_pending_events(user_id: str) -> list[dict]:
    """Get and clear pending events for a user (for SSE polling)."""
    events = _pending_events.pop(user_id, [])
    return events


def _build_event_message(event: RunEvent) -> str:
    """Build a human-readable message for a run event.
    
    Twin's style: factual, no apologies, concrete next steps.
    """
    name = event.agent_name

    if event.event_type == RunEventType.BUILD_SUCCESS:
        msg = f"✅ **{name}** build completed successfully."
        if event.summary:
            msg += f"\n\n{event.summary}"
        msg += "\n\nThe agent is ready to run."
        return msg

    elif event.event_type == RunEventType.BUILD_PARTIAL:
        msg = f"⚠️ **{name}** build partially completed."
        if event.error:
            msg += f"\n\nIssue: {event.error}"
        msg += "\n\nSome steps worked but there's a gap that needs fixing."
        return msg

    elif event.event_type == RunEventType.BUILD_FAIL:
        msg = f"❌ **{name}** build failed."
        if event.error:
            msg += f"\n\nError: {event.error}"
        return msg

    elif event.event_type == RunEventType.BUILD_STOPPED:
        msg = f"⏹️ **{name}** build was stopped."
        if event.summary:
            msg += f"\n\nStopped at: {event.summary}"
        return msg

    elif event.event_type == RunEventType.RUN_SUCCESS:
        msg = f"✅ **{name}** run completed successfully."
        if event.summary:
            msg += f"\n\n{event.summary}"
        if event.output:
            msg += f"\n\n**Output:**\n{event.output[:300]}"
        return msg

    elif event.event_type == RunEventType.RUN_PARTIAL:
        msg = f"⚠️ **{name}** run partially completed."
        if event.error:
            msg += f"\n\nIssue: {event.error}"
        if event.output:
            msg += f"\n\n**What worked:**\n{event.output[:200]}"
        return msg

    elif event.event_type == RunEventType.RUN_FAIL:
        msg = f"❌ **{name}** run failed."
        if event.error:
            msg += f"\n\nError: {event.error}"
        return msg

    elif event.event_type == RunEventType.RUN_STOPPED:
        msg = f"⏹️ **{name}** run was stopped."
        return msg

    elif event.event_type == RunEventType.WAITING_FOR_INPUT:
        msg = f"💬 **{name}** is waiting for your input."
        if event.summary:
            msg += f"\n\n{event.summary}"
        return msg

    return f"Event received for **{name}**: {event.event_type.value}"


async def _forward_to_chat(user_id: str, event: dict, headers: dict) -> None:
    """Forward a run event to the chat service for real-time user notification.
    
    If the user is connected to the chat service, they'll see the event
    and follow-up options in real time.
    """
    chat_url = settings.CHAT_SERVICE_URL
    if not chat_url:
        return

    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as c:
            await c.post(
                f"{chat_url}/chat/event",
                json={
                    "user_id": user_id,
                    "event": event,
                    "source": "agent_architect",
                },
                headers=headers,
            )
    except Exception as e:
        logger.debug(f"[RUN_EVENT] Could not forward to chat: {e}")
