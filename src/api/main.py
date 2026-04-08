"""Twin Platform — FastAPI Application"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from src.orchestrator.orchestrator import Orchestrator

app = FastAPI(title="Twin Platform", version="1.0.0")

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

class RunEventRequest(BaseModel):
    workspace_id: str
    type: str
    outcome: str
    agent_id: str = ""
    run_id: str = ""


def get_orchestrator(workspace_id: str) -> Orchestrator:
    if workspace_id not in orchestrators:
        orchestrators[workspace_id] = Orchestrator(workspace_id)
    return orchestrators[workspace_id]


@app.post("/api/message")
async def handle_message(req: MessageRequest):
    orch = get_orchestrator(req.workspace_id)
    return await orch.handle_message(req.message)

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
