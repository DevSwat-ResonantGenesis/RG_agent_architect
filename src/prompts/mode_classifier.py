"""Mode Classification — BRAINSTORM / CONTROL / REVIEW"""
from src.models.agent import OperationMode

BRAINSTORM_SIGNALS = ["what can you do", "help me", "automate", "ideas", "suggest"]
CONTROL_SIGNALS = ["monitor", "send", "scrape", "search", "create", "build", "run", "schedule", "delete"]
REVIEW_SIGNALS = ["what happened", "why did it fail", "credits", "status", "results", "history"]


def classify_mode(message: str, agents_exist: bool) -> OperationMode:
    msg = message.lower()
    scores = {
        OperationMode.BRAINSTORM: sum(1 for s in BRAINSTORM_SIGNALS if s in msg),
        OperationMode.CONTROL: sum(1 for s in CONTROL_SIGNALS if s in msg),
        OperationMode.REVIEW: sum(1 for s in REVIEW_SIGNALS if s in msg),
    }
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    return OperationMode.CONTROL if agents_exist else OperationMode.BRAINSTORM
