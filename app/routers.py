"""
RG Agent Architect — API Routers

REST + SSE streaming endpoints.
Twin architecture: twin.md full orchestrator surface.

Endpoints:
  POST /architect/orchestrate          — Main orchestration (chat → structured response)
  POST /architect/orchestrate/stream   — SSE streaming orchestration
  POST /architect/classify-intent      — Intent classification for routing
  POST /architect/health-check         — Proactive agent health scan
  POST /architect/run-complete         — Post-run health webhook
  POST /architect/run-event            — Twin run event state machine webhook
  GET  /architect/events/{user_id}     — Pending events polling
  GET  /architect/events/{user_id}/stream — Event SSE stream
  GET  /architect/health               — Container health
"""
import asyncio
import json
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
    """Main entry point. Chat service sends user message, gets structured response."""
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
    """SSE streaming orchestration. Events: status, thinking, tool_call, tool_result, done."""
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
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/classify-intent")
async def classify_intent_endpoint(req: ClassifyRequest):
    """Standalone intent classification for chat service routing."""
    return {"intent": "agent_architect", "message": req.message[:200]}


@router.post("/health-check")
async def health_check_endpoint(req: HealthCheckRequest, request: Request):
    """Proactive health scan across all agents. Detects failures, stuck sessions, depleted budgets."""
    headers = _extract_headers(request)
    result = await run_health_check(headers=headers, auto_fix=req.auto_fix)
    return result


@router.post("/run-complete")
async def run_complete_webhook(req: RunCompleteWebhook, request: Request):
    """Post-run health webhook. Auto-fixes patterns of failure."""
    headers = _extract_headers(request)
    result = await check_agent_after_run(
        agent_id=req.agent_id,
        session_status=req.session_status,
        headers=headers,
    )
    return {"checked": True, "fix_applied": result}


@router.post("/run-event")
async def run_event_webhook(req: RunEventRequest, request: Request):
    """Twin run event state machine webhook (twin.md lines 449-459).

    Classifies event type, generates follow-up options, forwards to chat.
    NEVER auto-triggers build/run unless user explicitly asked.
    """
    headers = _extract_headers(request)
    if not headers.get("x-user-id") and req.user_id:
        headers["x-user-id"] = req.user_id
    result = await process_run_event(req.model_dump(), headers)
    return result


@router.get("/events/{user_id}")
async def get_user_events(user_id: str):
    """Get and clear pending run events for a user."""
    events = get_pending_events(user_id)
    return {"events": events, "count": len(events)}


@router.get("/events/{user_id}/stream")
async def stream_user_events(user_id: str):
    """SSE stream of run events. Long-poll: 30s window, 2s interval."""
    async def event_generator():
        yield f"data: {json.dumps({'type': 'connected', 'user_id': user_id})}\n\n"
        for _ in range(15):
            events = get_pending_events(user_id)
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
            await asyncio.sleep(2)
        yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/health")
async def health():
    return {"status": "healthy", "service": "agent_architect"}


# ── Helpers ──

def _extract_headers(request: Request) -> dict[str, str]:
    """Extract forwarded auth headers."""
    return {
        "x-user-id": request.headers.get("x-user-id", ""),
        "x-user-role": request.headers.get("x-user-role", "user"),
        "x-is-superuser": request.headers.get("x-is-superuser", "false"),
        "x-unlimited-credits": request.headers.get("x-unlimited-credits", "false"),
    }
