"""Mode Classification — BRAINSTORM / CONTROL / REVIEW / DIAGNOSE

Key insight: "I want to build an agent" is BRAINSTORM (vague desire, no concrete goal).
"Build an agent that scrapes YC for 2026 startups" is CONTROL (specific, actionable).
The difference: does the message contain a concrete outcome/goal AFTER the action verb?
"""
import re
from src.models.agent import OperationMode

REVIEW_SIGNALS = ["what happened", "why did it fail", "credits", "status", "results",
                  "history", "show my agent", "list agent", "how many agent"]
DIAGNOSE_SIGNALS = ["not working", "why does it", "keep failing", "output is bad",
                    "broken", "fix", "diagnose", "debug"]

# These phrases are vague desires — user doesn't have a specific goal yet
_VAGUE_PATTERNS = [
    r"^i\s+want\s+(?:to\s+)?(?:build|create|make)\s+(?:an?\s+)?agent\s*$",
    r"^(?:build|create|make)\s+(?:me\s+)?(?:an?\s+)?agent\s*$",
    r"^i\s+(?:need|want)\s+(?:an?\s+)?agent\s*$",
    r"^(?:can you|help me)\s+(?:build|create|make)",
    r"^(?:let'?s|i want to)\s+(?:build|create|make)\s+(?:something|an? agent)",
    r"^(?:build|create)\s+(?:a\s+)?new\s+agent\s*$",
    r"^i\s+want\s+(?:to\s+)?automate",
    r"^what\s+(?:can you|agents? can)\s+do",
    r"^help\s+me\s+(?:with|build|create|automate)",
    r"^i\s+(?:want|need)\s+(?:to\s+)?(?:build|create|make)\s+(?:an?\s+)?agent\s+(?:for|to)\s*$",
]

# Specific action — user has a concrete goal
_SPECIFIC_ACTION_PATTERNS = [
    r"(?:build|create|make)\s+(?:an?\s+)?(?:agent\s+)?(?:that|which|to)\s+\w{3,}",
    r"(?:monitor|scrape|search|send|fetch|track|analyze|scan|research)\s+\w{3,}",
    r"(?:run|start|stop|delete|schedule|modify|update|rename)\s+(?:my\s+)?agent",
    r"(?:add|remove)\s+(?:tool|trigger)",
    r"(?:set|change)\s+(?:trigger|schedule|interval)",
]


def classify_mode(message: str, agents_exist: bool) -> OperationMode:
    msg = message.strip()
    msg_lower = msg.lower()

    # Check review/diagnose first (highest priority — user asking about existing state)
    review_score = sum(1 for s in REVIEW_SIGNALS if s in msg_lower)
    diagnose_score = sum(1 for s in DIAGNOSE_SIGNALS if s in msg_lower)
    if diagnose_score > 0:
        return OperationMode.DIAGNOSE if hasattr(OperationMode, "DIAGNOSE") else OperationMode.REVIEW
    if review_score > 0:
        return OperationMode.REVIEW

    # Check if message is a vague desire (→ BRAINSTORM)
    for pattern in _VAGUE_PATTERNS:
        if re.search(pattern, msg_lower):
            return OperationMode.BRAINSTORM

    # Check if message has a specific actionable goal (→ CONTROL)
    for pattern in _SPECIFIC_ACTION_PATTERNS:
        if re.search(pattern, msg_lower):
            return OperationMode.CONTROL

    # Short messages without specific goals are brainstorm
    word_count = len(msg.split())
    if word_count <= 6 and any(w in msg_lower for w in ["build", "create", "make", "agent"]):
        return OperationMode.BRAINSTORM

    # Default: CONTROL if agents exist (user likely managing), BRAINSTORM if empty workspace
    return OperationMode.CONTROL if agents_exist else OperationMode.BRAINSTORM
