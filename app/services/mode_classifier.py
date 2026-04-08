"""
RG Agent Architect — Mode Classification

Twin mode_classification (twin.md lines 369-373):
- Brainstorm: vague, exploring, thinking out loud
- Control: specific actionable goal (most common)
- Review: asking about past results, costs, status

Rule: When ambiguous → Control if agents exist, Brainstorm if they don't.

Derived from twin-platform/src/prompts/mode_classifier.py
"""
from enum import Enum
from typing import List


class OperationMode(str, Enum):
    BRAINSTORM = "brainstorm"
    CONTROL = "control"
    REVIEW = "review"


BRAINSTORM_SIGNALS = [
    "what can you do", "help me", "automate", "ideas", "suggest",
    "what should i", "what could i", "i want to", "i need to",
    "how can i", "what's possible", "explore", "think about",
    "brainstorm", "not sure what", "any ideas",
]

CONTROL_SIGNALS = [
    "monitor", "send", "scrape", "search", "create", "build", "run",
    "schedule", "delete", "stop", "modify", "update", "set up",
    "configure", "connect", "add", "remove", "change", "fix",
    "rebuild", "trigger", "email", "track", "fetch", "check",
]

REVIEW_SIGNALS = [
    "what happened", "why did it fail", "credits", "status",
    "results", "history", "how much", "cost", "show me",
    "what did", "last run", "recent", "summary", "details",
    "how many", "billing", "plan", "usage",
]


def classify_mode(message: str, agents_exist: bool) -> OperationMode:
    """Classify user message into Brainstorm / Control / Review.

    Uses keyword signal matching with fallback to agent-existence heuristic.
    """
    msg = message.lower()

    scores = {
        OperationMode.BRAINSTORM: sum(1 for s in BRAINSTORM_SIGNALS if s in msg),
        OperationMode.CONTROL: sum(1 for s in CONTROL_SIGNALS if s in msg),
        OperationMode.REVIEW: sum(1 for s in REVIEW_SIGNALS if s in msg),
    }

    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best

    # Ambiguous fallback (twin.md line 373)
    return OperationMode.CONTROL if agents_exist else OperationMode.BRAINSTORM
