"""Resonant Agent Architect — FastAPI Application with SSE streaming"""
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Dict, List, Optional

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from src.orchestrator.orchestrator import Orchestrator
from src.prompts.router import preload_prompt_router, get_router
from src.builder.agent_type_classifier import preload_agent_type_classifier, get_agent_type_classifier

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-train/load neural classifiers on startup."""
    await preload_prompt_router()
    await preload_agent_type_classifier()
    yield

app = FastAPI(title="Resonant Agent Architect", version="2.0.0", lifespan=lifespan)

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
    context: str = ""  # previous assistant content (backward compat)
    conversation_history: List[Dict] = []  # [{"role": "user", "content": "..."}]

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


def _inject_conversation_history(orch: Orchestrator, req: MessageRequest):
    """Inject chat conversation history into the orchestrator so it has context.
    Only injects on first message (empty history) to avoid duplication."""
    if not orch.history and req.conversation_history:
        for msg in req.conversation_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                orch.history.append({"role": role, "content": content[:500]})
    elif not orch.history and req.context:
        # Backward compat: inject prev_assistant_content as single context message
        orch.history.append({"role": "assistant", "content": req.context[:1000]})


@app.post("/api/message")
async def handle_message(req: MessageRequest):
    """Synchronous JSON response (backward compatible)."""
    orch = get_orchestrator(req.workspace_id, req.user_id)
    _inject_conversation_history(orch, req)
    return await orch.handle_message(req.message)


@app.post("/api/message/stream")
async def handle_message_stream(req: MessageRequest):
    """SSE streaming endpoint — yields real-time progress events.

    Event types: session_start, thinking, text, tool_call, tool_result,
                 summarizing, error, complete
    """
    orch = get_orchestrator(req.workspace_id, req.user_id)
    _inject_conversation_history(orch, req)

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


@app.get("/api/prompt-router/stats")
async def prompt_router_stats():
    """Get neural prompt classifier statistics."""
    router = get_router()
    return router.get_stats()


@app.post("/api/prompt-router/retrain")
async def prompt_router_retrain():
    """Retrain the prompt classifier with accumulated active learning data."""
    router = get_router()
    stats = await router.retrain()
    return {"status": "retrained", "stats": stats}


@app.get("/api/agent-type-classifier/stats")
async def agent_type_classifier_stats():
    """Get agent type classifier statistics."""
    clf = get_agent_type_classifier()
    return clf.get_stats()


@app.post("/api/agent-type-classifier/retrain")
async def agent_type_classifier_retrain():
    """Retrain agent type classifier with accumulated active learning data."""
    clf = get_agent_type_classifier()
    stats = await clf.retrain()
    return {"status": "retrained", "stats": stats}


@app.post("/api/agent-type-classifier/classify")
async def classify_agent_type(req: dict):
    """Classify an agent type from goal + tools (for testing/debugging)."""
    clf = get_agent_type_classifier()
    await clf.ensure_ready()
    result = clf.classify(
        goal=req.get("goal", ""),
        tools=req.get("tools"),
    )
    return result
