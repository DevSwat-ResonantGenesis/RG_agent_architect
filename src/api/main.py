"""Resonant Agent Architect — FastAPI Application with SSE streaming"""
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Dict, List, Optional

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from src.orchestrator.orchestrator import Orchestrator
from src.prompts.router import preload_prompt_router, get_router
from src.builder.agent_type_classifier import preload_agent_type_classifier, get_agent_type_classifier
from src.orchestrator.tool_classifier import architect_tool_classifier
from src.services import ml_model_store

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB tables, then pre-train/load neural classifiers on startup."""
    if ml_model_store.is_available():
        await ml_model_store.ensure_tables()
        logger.info("[Startup] ML model DB tables ready")
    else:
        logger.warning("[Startup] No DATABASE_URL — ML models will NOT persist across restarts")
    await preload_prompt_router()
    await preload_agent_type_classifier()
    await _preload_tool_classifier()
    yield


async def _preload_tool_classifier():
    """Train the architect tool classifier at startup (not lazily)."""
    import asyncio
    import time

    async def _train():
        t0 = time.time()
        try:
            ok = await architect_tool_classifier.ensure_ready()
            elapsed = (time.time() - t0) * 1000
            if ok:
                stats = architect_tool_classifier.get_stats()
                print(
                    f"[ArchitectToolClassifier] Trained in {elapsed:.0f}ms — "
                    f"{stats['stats'].get('n_groups', '?')} groups, "
                    f"{stats['stats'].get('n_samples', 0)} samples, "
                    f"accuracy={stats['stats'].get('accuracy', 0)}",
                    flush=True,
                )
            else:
                print(f"[ArchitectToolClassifier] Training FAILED in {elapsed:.0f}ms", flush=True)
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            print(f"[ArchitectToolClassifier] Training error ({elapsed:.0f}ms): {e}", flush=True)

    asyncio.create_task(_train())

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
    user_api_keys: Dict = {}  # BYOK keys forwarded from chat service
    preferred_provider: str = ""  # user-selected provider override, forwarded from chat service
    preferred_model: str = ""  # user-selected model override, forwarded from chat service
    client_timezone: str = ""  # IANA tz from the user's browser, forwarded from chat service

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
    Only injects on first message (empty history) to avoid duplication.
    Builds a timeline-aware context so the LLM knows message ordering."""
    if not orch.history and req.conversation_history:
        # Sort by timestamp if available to ensure correct order
        sorted_msgs = sorted(
            req.conversation_history,
            key=lambda m: m.get("timestamp", ""),
        )
        for msg in sorted_msgs:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                orch.history.append({"role": role, "content": content[:1000]})
    elif not orch.history and req.context:
        orch.history.append({"role": "assistant", "content": req.context[:1000]})


def _apply_auth_context(orch: Orchestrator, request: Request):
    """Forward auth headers from chat service to orchestrator for downstream calls."""
    orch._is_superuser = request.headers.get("x-is-superuser", "false").lower() in ("true", "1")
    orch._unlimited_credits = request.headers.get("x-unlimited-credits", "false").lower() in ("true", "1")
    orch._user_role = request.headers.get("x-user-role", "user")


@app.post("/api/message")
async def handle_message(req: MessageRequest, request: Request):
    """Synchronous JSON response (backward compatible)."""
    orch = get_orchestrator(req.workspace_id, req.user_id)
    if req.user_api_keys:
        orch._user_api_keys = req.user_api_keys
    orch._preferred_provider = req.preferred_provider
    orch._preferred_model = req.preferred_model
    orch._client_timezone = req.client_timezone
    _apply_auth_context(orch, request)
    _inject_conversation_history(orch, req)
    return await orch.handle_message(req.message)


@app.post("/api/message/stream")
async def handle_message_stream(req: MessageRequest, request: Request):
    """SSE streaming endpoint — yields real-time progress events.

    Event types: session_start, thinking, text, tool_call, tool_result,
                 summarizing, error, complete
    """
    orch = get_orchestrator(req.workspace_id, req.user_id)
    if req.user_api_keys:
        orch._user_api_keys = req.user_api_keys
        print(f"[Architect] BYOK keys received: {list(req.user_api_keys.keys())}", flush=True)
    else:
        print("[Architect] WARNING: No BYOK keys received from chat service", flush=True)
    orch._preferred_provider = req.preferred_provider
    orch._preferred_model = req.preferred_model
    orch._client_timezone = req.client_timezone
    _apply_auth_context(orch, request)
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


@app.get("/api/tool-classifier/stats")
async def tool_classifier_stats():
    """Get architect tool classifier statistics."""
    return architect_tool_classifier.get_stats()


@app.post("/api/tool-classifier/predict")
async def tool_classifier_predict(req: dict):
    """Predict tool group for a message (for testing/debugging)."""
    await architect_tool_classifier.ensure_ready()
    tools, group = architect_tool_classifier.get_tools_for_message(req.get("message", ""))
    return {"group": group, "tools": tools, "n_tools": len(tools)}
