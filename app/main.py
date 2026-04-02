"""
RG Agent Architect — FastAPI Application
Standalone orchestrator service for building and running autonomous agents.
"""
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

app = FastAPI(
    title="RG Agent Architect",
    version="1.0.0",
    description="Standalone orchestrator for building and running autonomous agents on Resonant Genesis.",
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
async def health():
    return {
        "status": "healthy",
        "service": "rg_agent_architect",
        "version": "1.0.0",
    }
