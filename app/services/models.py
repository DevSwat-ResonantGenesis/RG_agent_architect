"""
RG Agent Architect — Data Models

Twin architecture data models for build sessions, run events,
workspace state, and scope risk analysis.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# ENUMS — Twin's state machine states
# ═══════════════════════════════════════════════════════════════

class RunEventType(str, Enum):
    """Twin's run event classification."""
    BUILD_SUCCESS = "build_success"
    BUILD_PARTIAL = "build_partial"
    BUILD_FAIL = "build_fail"
    BUILD_STOPPED = "build_stopped"
    RUN_SUCCESS = "run_success"
    RUN_PARTIAL = "run_partial"
    RUN_FAIL = "run_fail"
    RUN_STOPPED = "run_stopped"
    WAITING_FOR_INPUT = "waiting_for_input"


class OperationMode(str, Enum):
    """Twin's 3 modes of operation."""
    BRAINSTORM = "brainstorm"
    CONTROL = "control"
    REVIEW = "review"


class DispatchAction(str, Enum):
    """Twin's dispatching actions."""
    CREATE = "create"
    EXTEND = "extend"
    RUN = "run"
    GUIDE = "guide"
    SCHEDULE = "schedule"
    DELETE = "delete"


class ScopeRiskLevel(str, Enum):
    """Twin's scope risk levels."""
    HIGH = "high"
    MODERATE = "moderate"
    SAFE = "safe"


# ═══════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════

@dataclass
class RunEvent:
    """A run or build event received from the Agent Engine.
    
    Twin's Run Event Processing state machine (twin.md Section 6/lines 1188-1253):
    - Classify: build event or run event
    - Determine outcome: success/partial/fail/stopped/waiting
    - Generate follow-up options via present_options
    - NEVER auto-trigger build/run unless user explicitly asked
    """
    agent_id: str
    agent_name: str
    event_type: RunEventType
    session_id: str = ""
    summary: str = ""
    error: str = ""
    output: str = ""
    tool_calls: list = field(default_factory=list)
    has_trigger: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def follow_up_options(self) -> list[dict]:
        """Generate Twin-style follow-up options based on event type.
        
        From twin.md Run Event Processing decision tree.
        """
        if self.event_type == RunEventType.BUILD_SUCCESS:
            options = [{"label": "Try autonomous run", "value": "run_agent"}]
            if not self.has_trigger:
                options.insert(0, {"label": "Set up trigger", "value": "set_trigger"})
            options.append({"label": "Build UI", "value": "open_interface_editor"})
            return options

        elif self.event_type in (RunEventType.BUILD_PARTIAL, RunEventType.BUILD_FAIL):
            return [
                {"label": "Fix the issue", "value": "continue_build"},
                {"label": "Different approach", "value": "rebuild"},
                {"label": "Show full details", "value": "run_snapshot"},
            ]

        elif self.event_type == RunEventType.BUILD_STOPPED:
            return [
                {"label": "Resume building", "value": "continue_build"},
                {"label": "Start fresh", "value": "rebuild"},
                {"label": "Show full details", "value": "run_snapshot"},
            ]

        elif self.event_type == RunEventType.RUN_SUCCESS:
            options = [
                {"label": "Run again", "value": "run_agent"},
                {"label": "Make changes", "value": "continue_build"},
            ]
            if not self.has_trigger:
                options.append({"label": "Set up schedule", "value": "set_trigger"})
            return options

        elif self.event_type in (RunEventType.RUN_PARTIAL, RunEventType.RUN_FAIL):
            return [
                {"label": "Fix with rebuild", "value": "continue_build"},
                {"label": "Run again", "value": "run_agent"},
                {"label": "Show full details", "value": "run_snapshot"},
            ]

        elif self.event_type == RunEventType.WAITING_FOR_INPUT:
            return [
                {"label": "Provide input", "value": "message_build"},
            ]

        return []


@dataclass
class ScopeRisk:
    """Scope risk analysis result.
    
    Twin's Scope Risk Analysis (twin.md Section 5/lines 1144-1185):
    HIGH: entity discovery, per-entity HTTP, geographic fan-out, unbounded
    MODERATE: implicit large scope, multi-step pipelines
    SAFE: single API, explicit small bounds, single entity
    """
    level: ScopeRiskLevel
    reason: str = ""
    recommendation: str = ""

    HIGH_PATTERNS = [
        "all companies", "every restaurant", "all businesses",
        "all listings", "all properties", "all leads",
        "across all", "every city", "all major",
        "check each website", "scrape each",
        "find all", "scrape all",
    ]

    MODERATE_PATTERNS = [
        "companies in", "businesses in", "without",
        "find → check", "find then", "search and scrape",
    ]

    @classmethod
    def analyze(cls, goal: str) -> "ScopeRisk":
        """Analyze a goal for scope risk. Returns ScopeRisk with level and reason."""
        goal_lower = goal.lower()

        # Check HIGH risk patterns
        for pattern in cls.HIGH_PATTERNS:
            if pattern in goal_lower:
                return cls(
                    level=ScopeRiskLevel.HIGH,
                    reason=f"Goal contains '{pattern}' — could fan out into thousands of operations",
                    recommendation="Consider adding explicit bounds (e.g. 'top 10', 'first 50') or use a sample first",
                )

        # Check MODERATE risk patterns
        for pattern in cls.MODERATE_PATTERNS:
            if pattern in goal_lower:
                return cls(
                    level=ScopeRiskLevel.MODERATE,
                    reason=f"Goal contains '{pattern}' — could expand beyond expectations",
                    recommendation="May want to bound the scope or test with a small sample first",
                )

        return cls(level=ScopeRiskLevel.SAFE)


@dataclass
class BuildSession:
    """Tracks an agent build session.
    
    Twin distinguishes between Builder (high-reasoning, expensive) and
    Runner (fast, cheap). Build sessions track the builder's work.
    """
    agent_id: str
    agent_name: str
    session_id: str = ""
    status: str = "pending"  # pending, building, completed, failed, stopped
    instructions_written: bool = False
    tools_discovered: list = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    error: str = ""


@dataclass
class WorkspaceState:
    """Cached workspace state for session initialization.
    
    Twin's Session Init Protocol (twin.md Section 1/lines 1025-1042):
    3 parallel calls at session start: workspace_snapshot + list_workspace_tools + get_user_memory
    """
    user_id: str
    agents: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    tools_by_category: dict = field(default_factory=dict)
    memory_facts: list = field(default_factory=list)
    workspace_name: str = ""
    workspace_icon: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_agents(self) -> bool:
        return len(self.agents) > 0

    @property
    def agent_count(self) -> int:
        return len(self.agents)

    def find_agent(self, name: str) -> Optional[dict]:
        """Find agent by name (case-insensitive)."""
        name_lower = name.lower().strip()
        for a in self.agents:
            if (a.get("name") or "").lower() == name_lower:
                return a
        for a in self.agents:
            if name_lower in (a.get("name") or "").lower():
                return a
        return None
