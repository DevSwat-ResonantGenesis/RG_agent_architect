"""
RG Agent Architect — API Routers
Clean REST endpoints that delegate to the orchestrator.
"""
import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .services.orchestrator import orchestrate

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


@router.post("/classify-intent")
async def classify_intent_endpoint(req: ClassifyRequest):
    """Standalone intent classification (used by chat service for routing)."""
    from .services.orchestrator import _classify_intent
    intent = await _classify_intent(req.message, req.user_api_keys)
    return {"intent": intent, "message": req.message[:200]}


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
