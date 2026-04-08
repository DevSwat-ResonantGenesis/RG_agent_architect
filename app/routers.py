"""
RG Agent Architect — API Routers
REST + SSE streaming endpoints that delegate to the orchestrator.
"""
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .services.orchestrator import orchestrate, orchestrate_stream
from .services.health_monitor import run_health_check, check_agent_after_run
from .services.run_events import process_run_event, get_pending_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/architect", tags=["Agent Architect"])


# ── Request / Response Models ──

class OrchestrateRequest(BaseModel):
    message: str
    user_id: str
    context: dict[str, Any] = {}
    user_api_keys: dict[str, str] = {}


class ClassifyRequest(BaseModel):
    message: str
    user_api_keys: dict[str, str] = {}


class HealthCheckRequest(BaseModel):
    auto_fix: bool = False


class RunCompleteWebhook(BaseModel):
    agent_id: str
    session_status: str


class RunEventRequest(BaseModel):
    agent_id: str
    agent_name: str = ""
    session_id: str = ""
    event_type: str = ""
    status: str = ""
    is_build: bool = False
    summary: str = ""
    error: str = ""
    output: Any = None
    tool_calls: list = []
    has_trigger: bool = False
    user_id: str = ""


# ── Endpoints ──

@router.post("/orchestrate")
async def orchestrate_endpoint(req: OrchestrateRequest, request: Request):
    """Main entry point. Chat service calls this with a user message
    and gets back a structured response with summary, options, and metadata.
    """
    headers = _extract_headers(request)
    if not headers.get("x-user-id"):
        headers["x-user-id"] = req.user_id

    result = await orchestrate(
        message=req.message,
        user_id=req.user_id,
        context=req.context,
        headers=headers,
        user_api_keys=req.user_api_keys,
    )
    return result


@router.post("/orchestrate/stream")
async def orchestrate_stream_endpoint(req: OrchestrateRequest, request: Request):
    """SSE streaming version of orchestrate. Streams real-time events:
    - status: context gathering progress
    - thinking: ReAct iteration number
    - tool_call: which tool is being called
    - tool_result: tool execution result
    - done: final structured response (same format as /orchestrate)
    """
    headers = _extract_headers(request)
    if not headers.get("x-user-id"):
        headers["x-user-id"] = req.user_id

    async def event_generator():
        async for event in orchestrate_stream(
            message=req.message,
            user_id=req.user_id,
            context=req.context,
            headers=headers,
            user_api_keys=req.user_api_keys,
        ):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/classify-intent")
async def classify_intent_endpoint(req: ClassifyRequest):
    """Standalone intent classification (used by chat service for routing).
    Simplified — always returns 'agent_architect' since this service only handles architect requests."""
    return {"intent": "agent_architect", "message": req.message[:200]}


@router.post("/health-check")
async def health_check_endpoint(req: HealthCheckRequest, request: Request):
    """Run proactive health check across all user agents.
    Detects consecutive failures, stuck sessions, depleted budgets.
    Pass auto_fix=true to automatically apply recommended fixes.
    """
    headers = _extract_headers(request)
    result = await run_health_check(headers=headers, auto_fix=req.auto_fix)
    return result


@router.post("/run-complete")
async def run_complete_webhook(req: RunCompleteWebhook, request: Request):
    """Webhook called after each agent run completes.
    Triggers lightweight post-run health check with auto-fix.
    """
    headers = _extract_headers(request)
    result = await check_agent_after_run(
        agent_id=req.agent_id,
        session_status=req.session_status,
        headers=headers,
    )
    return {"checked": True, "fix_applied": result}


@router.post("/run-event")
async def run_event_webhook(req: RunEventRequest, request: Request):
    """Webhook called by Agent Engine when a build or run completes.
    
    Twin's Run Event Processing (twin.md Section 6):
    - Classifies event type (build/run × success/partial/fail/stopped)
    - Generates follow-up options per Twin's decision tree
    - Forwards to chat service for real-time user notification
    - Stores for SSE polling
    """
    headers = _extract_headers(request)
    if not headers.get("x-user-id") and req.user_id:
        headers["x-user-id"] = req.user_id

    result = await process_run_event(req.model_dump(), headers)
    return result


@router.get("/events/{user_id}")
async def get_user_events(user_id: str):
    """Get pending run events for a user (for SSE polling).
    Returns and clears any queued events."""
    events = get_pending_events(user_id)
    return {"events": events, "count": len(events)}


@router.get("/events/{user_id}/stream")
async def stream_user_events(user_id: str):
    """SSE stream of run events for a user. Long-poll style — returns
    events as they arrive, keeps connection open."""
    import asyncio
    import json

    async def event_generator():
        # Send initial keepalive
        yield f"data: {json.dumps({'type': 'connected', 'user_id': user_id})}\n\n"
        
        # Poll for events every 2 seconds, up to 30 seconds
        for _ in range(15):
            events = get_pending_events(user_id)
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
            await asyncio.sleep(2)
        
        # Send keepalive before closing
        yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/health")
async def health():
    return {"status": "healthy", "service": "agent_architect"}


# ── Helpers ──

def _extract_headers(request: Request) -> dict[str, str]:
    """Extract forwarded auth headers from the incoming request."""
    return {
        "x-user-id": request.headers.get("x-user-id", ""),
        "x-user-role": request.headers.get("x-user-role", "user"),
        "x-is-superuser": request.headers.get("x-is-superuser", "false"),
        "x-unlimited-credits": request.headers.get("x-unlimited-credits", "false"),
    }
