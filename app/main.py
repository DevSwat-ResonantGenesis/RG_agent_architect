"""
RG Agent Architect — FastAPI Application

Twin architecture orchestrator service.
Manages agent lifecycle, workspace context, and real-time event processing.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

app = FastAPI(
    title="RG Agent Architect",
    description="Twin architecture orchestrator — manages agent lifecycle via ReAct loop",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def root_health():
    return {"status": "healthy", "service": "agent_architect", "version": "2.0.0"}
