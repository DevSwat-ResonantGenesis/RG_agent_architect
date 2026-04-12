"""Resonant Agent Architect — FastAPI Application with SSE streaming"""
import json
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from src.orchestrator.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

app = FastAPI(title="Resonant Agent Architect", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrators: dict = {}


class MessageRequest(BaseModel):
    workspace_id: str
    message: str
    user_id: str = ""

class RunEventRequest(BaseModel):
    workspace_id: str
    type: str
    outcome: str
    agent_id: str = ""
    run_id: str = ""


def get_orchestrator(workspace_id: str, user_id: str = "") -> Orchestrator:
    if workspace_id not in orchestrators:
        orchestrators[workspace_id] = Orchestrator(workspace_id, user_id=user_id)
    return orchestrators[workspace_id]


@app.post("/api/message")
async def handle_message(req: MessageRequest):
    """Synchronous JSON response (backward compatible)."""
    orch = get_orchestrator(req.workspace_id, req.user_id)
    return await orch.handle_message(req.message)


@app.post("/api/message/stream")
async def handle_message_stream(req: MessageRequest):
    """SSE streaming endpoint — yields real-time progress events.

    Event types: session_start, thinking, text, tool_call, tool_result,
                 summarizing, error, complete
    """
    orch = get_orchestrator(req.workspace_id, req.user_id)

    async def event_generator():
        try:
            async for event in orch.handle_message_stream(req.message):
                data = json.dumps(event, default=str)
                yield f"data: {data}\n\n"
        except Exception as e:
            logger.error(f"[SSE] Stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/run-event")
async def handle_run_event(req: RunEventRequest):
    orch = get_orchestrator(req.workspace_id)
    return await orch.handle_run_event(req.dict())

@app.get("/api/workspace/{workspace_id}")
async def get_workspace(workspace_id: str):
    orch = get_orchestrator(workspace_id)
    return await orch.initialize_session()

@app.get("/health")
async def health():
    return {"status": "ok"}
