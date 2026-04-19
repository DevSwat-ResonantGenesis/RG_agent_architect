"""Data Models — Workspace → Agent → Run (3-layer architecture)"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class RunOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    STOPPED = "Stopped"


class OperationMode(str, Enum):
    BRAINSTORM = "brainstorm"
    CONTROL = "control"
    REVIEW = "review"
    DIAGNOSE = "diagnose"


@dataclass
class Run:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = ""
    outcome: Optional[RunOutcome] = None
    summary: str = ""
    loop_count: int = 0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tokens_used: int = 0
    errors: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


@dataclass
class Trigger:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trigger_type: str = "time"
    interval: str = "daily"
    repeat_interval: int = 1
    timezone: str = "UTC"
    webhook_url: Optional[str] = None
    enabled: bool = True


@dataclass
class Agent:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    goal: str = ""
    icon: str = "🤖"
    system_prompt: str = ""
    tools: List[str] = field(default_factory=list)
    triggers: List[Trigger] = field(default_factory=list)
    runs: List[Run] = field(default_factory=list)
    db_path: str = ""
    interface_url: Optional[str] = None
    needs_build: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    max_loops: int = 30
    temperature: float = 0.5
    model: str = "groq/llama-3.3-70b"


@dataclass
class Workspace:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "My Workspace"
    icon: str = "🏢"
    agents: List[Agent] = field(default_factory=list)
    owner_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
