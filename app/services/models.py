"""
RG Agent Architect — Data Models

Twin architecture data models derived from twin.md:
- RunEvent + state machine (Section 6: run_events, lines 449-459)
- ScopeRisk analysis (Section 5: scope_risk, lines 410-429)
- BuildSession tracking (Section 1: builder vs runner, lines 357-360)
- WorkspaceState (Section 1: session_start, lines 365-367)
- OperationMode (Section 4: mode_classification, lines 369-373)
- DispatchAction (Section 7: dispatching, lines 431-437)
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# ENUMS — Twin's state machine states
# ═══════════════════════════════════════════════════════════════

class RunEventType(str, Enum):
    """Twin run_events (twin.md lines 449-459)."""
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
    """Twin mode_classification (twin.md lines 369-373)."""
    BRAINSTORM = "brainstorm"
    CONTROL = "control"
    REVIEW = "review"


class DispatchAction(str, Enum):
    """Twin dispatching (twin.md lines 431-437)."""
    CREATE = "create"
    EXTEND = "extend"
    RUN = "run"
    GUIDE = "guide"
    SCHEDULE = "schedule"
    DELETE = "delete"


class ScopeRiskLevel(str, Enum):
    """Twin scope_risk (twin.md lines 410-429)."""
    HIGH = "high"
    MODERATE = "moderate"
    SAFE = "safe"


# ═══════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════

@dataclass
class RunEvent:
    """A run or build event from Agent Engine.

    Twin run_events decision tree (twin.md lines 449-459):
    - Build SUCCESS (no trigger) → ["Set up a trigger", "Create UI interface", "Try autonomous run"]
    - Build SUCCESS (has trigger) → ["Create UI interface", "Try autonomous run"]
    - Build PARTIAL/FAIL → run_snapshot → explain → ["Fix the issue", "Try different approach", "Show full details"]
    - Run SUCCESS → ["Run again", "Make changes", "Set up schedule"]
    - Run PARTIAL/FAIL → run_snapshot → explain → ["Fix with rebuild", "Run again", "Show full details"]

    CRITICAL: Never call run_agent, build_agent, or continue_build in response
    to a [Run Event] unless the user explicitly asked.
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
        """Generate Twin-style follow-up options per twin.md lines 454-458."""
        if self.event_type == RunEventType.BUILD_SUCCESS:
            opts = []
            if not self.has_trigger:
                opts.append({"label": "Set up a trigger", "value": "set_trigger"})
            opts.append({"label": "Create UI interface", "value": "open_interface_editor"})
            opts.append({"label": "Try autonomous run", "value": "run_agent"})
            return opts

        elif self.event_type in (RunEventType.BUILD_PARTIAL, RunEventType.BUILD_FAIL):
            return [
                {"label": "Fix the issue", "value": "continue_build"},
                {"label": "Try different approach", "value": "rebuild"},
                {"label": "Show full details", "value": "run_snapshot"},
            ]

        elif self.event_type == RunEventType.BUILD_STOPPED:
            return [
                {"label": "Resume building", "value": "continue_build"},
                {"label": "Start fresh", "value": "rebuild"},
            ]

        elif self.event_type == RunEventType.RUN_SUCCESS:
            return [
                {"label": "Run again", "value": "run_agent"},
                {"label": "Make changes", "value": "continue_build"},
                {"label": "Set up schedule", "value": "set_trigger"},
            ]

        elif self.event_type in (RunEventType.RUN_PARTIAL, RunEventType.RUN_FAIL):
            return [
                {"label": "Fix with rebuild", "value": "continue_build"},
                {"label": "Run again", "value": "run_agent"},
                {"label": "Show full details", "value": "run_snapshot"},
            ]

        elif self.event_type == RunEventType.WAITING_FOR_INPUT:
            return [{"label": "Provide input", "value": "message_build"}]

        return []


@dataclass
class ScopeRisk:
    """Scope risk analysis (twin.md lines 410-429).

    HIGH: entity discovery, per-entity HTTP, geographic fan-out, unbounded
    MODERATE: implicit large scope, multi-step pipelines
    SAFE: single API, explicit small bounds, single entity

    When risk detected → present_options: ["Build a small sample first", "Build full scope", "Adjust scope"]
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
        """Analyze a goal for scope risk per twin.md lines 412-428."""
        goal_lower = goal.lower()

        for pattern in cls.HIGH_PATTERNS:
            if pattern in goal_lower:
                return cls(
                    level=ScopeRiskLevel.HIGH,
                    reason=f"'{pattern}' — could fan out into thousands of operations",
                    recommendation="Add explicit bounds (e.g. 'top 10', 'first 50') or sample first",
                )

        for pattern in cls.MODERATE_PATTERNS:
            if pattern in goal_lower:
                return cls(
                    level=ScopeRiskLevel.MODERATE,
                    reason=f"'{pattern}' — could expand beyond expectations",
                    recommendation="Consider bounding scope or testing with a small sample",
                )

        return cls(level=ScopeRiskLevel.SAFE)


@dataclass
class BuildSession:
    """Tracks a builder session (twin.md lines 357-360).

    Builder = high-reasoning model, expensive, runs once per creation/rebuild.
    Runner = smaller cheap model, follows instructions.
    """
    agent_id: str
    agent_name: str
    session_id: str = ""
    status: str = "pending"
    instructions_written: bool = False
    tools_discovered: list = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    error: str = ""


@dataclass
class WorkspaceState:
    """Cached workspace state for session init (twin.md lines 365-367).

    Session start: call workspace_snapshot, get_user_memory, and
    list_workspace_tools in parallel.
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
