"""
RG Agent Architect — Goal Crafting Pipeline

Twin's 8-step goal validation and composition (twin.md lines 399-408):
1. Extract outcome from user message
2. Identify services/tools needed
3. Strip recurrence language (handle via set_trigger separately)
4. Strip secrets (passwords, API keys, tokens)
5. Smart defaults (bounds, result counts)
6. Compose 2-3 sentence goal
7. Scope risk check (HIGH / MODERATE / SAFE)
8. Present to user for confirmation

Derived from twin-platform/src/orchestrator/goal_crafter.py
"""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


class ScopeRisk(str, Enum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    SAFE = "SAFE"


@dataclass
class CraftedGoal:
    """Result of the 8-step goal crafting pipeline."""
    goal_text: str
    services: List[str]
    risk_level: ScopeRisk
    risk_reasons: List[str] = field(default_factory=list)
    schedule: Optional[str] = None
    assumptions: List[str] = field(default_factory=list)
    original_text: str = ""
    secrets_redacted: bool = False


# ── Scope Risk Patterns (twin.md lines 412-428) ──

HIGH_RISK_PATTERNS = [
    r"all\s+(companies|businesses|restaurants|listings|properties|leads)\s+in",
    r"scrape\s+all",
    r"find\s+all",
    r"across\s+all",
    r"every\s+(city|restaurant|company|business|listing)",
    r"all\s+major",
    r"check\s+each\s+website",
    r"scrape\s+each",
]

MODERATE_RISK_PATTERNS = [
    r"companies?\s+in\s+\w+\s+without",
    r"businesses?\s+in",
    r"check\s+each",
    r"find\s+then",
    r"search\s+and\s+scrape",
]

# ── Recurrence Patterns (twin.md line 402) ──

RECURRENCE_PATTERNS = [
    r"every\s+(\d+\s+)?(minute|hour|day|week|month)s?",
    r"\bdaily\b",
    r"\bweekly\b",
    r"\bhourly\b",
    r"\bmonthly\b",
    r"twice\s+a\s+(day|week)",
    r"every\s+(morning|evening|night)",
]

# ── Secret Patterns (twin.md line 403) ──

SECRET_PATTERNS = [
    r"(password|api_?key|token|secret|credential)\s*[:=]\s*\S+",
    r"(sk-|pk_|Bearer\s+)\S+",
]

# ── Service Identification Keywords ──

SERVICE_KEYWORDS = {
    "search": "web_search",
    "scrape": "scrape_page",
    "email": "send_email",
    "chart": "build_chart",
    "sheet": "google_sheets",
    "spreadsheet": "google_sheets",
    "linkedin": "scrape_platforms",
    "instagram": "scrape_platforms",
    "twitter": "scrape_platforms",
    "reddit": "scrape_platforms",
    "research": "deep_research",
    "stock": "stock_market_data",
    "market": "stock_market_data",
    "slide": "create_presentation",
    "presentation": "create_presentation",
    "image": "generate_media",
    "video": "generate_media",
    "doc": "documents",
    "document": "documents",
}


def craft_goal(raw_message: str, available_tools: List[str] = None) -> CraftedGoal:
    """Run the full 8-step goal crafting pipeline.

    Steps:
    1. Extract outcome (the raw message IS the outcome)
    2. Identify services from keywords
    3. Strip recurrence → handle separately via set_trigger
    4. Strip secrets → never pass creds in goal text
    5. Smart defaults → add bounds if missing
    6. Compose clean goal text
    7. Check scope risk
    8. Return CraftedGoal for user confirmation
    """
    available_tools = available_tools or list(SERVICE_KEYWORDS.values())
    original = raw_message

    # Step 3: Strip recurrence
    goal_text, schedule = _strip_recurrence(raw_message)

    # Step 4: Strip secrets
    goal_text, secrets_found = _strip_secrets(goal_text)

    # Step 2: Identify services
    services = _identify_services(goal_text, available_tools)

    # Step 5: Smart defaults
    assumptions = _apply_defaults(goal_text)

    # Step 7: Scope risk check
    risk_level, risk_reasons = _check_scope_risk(goal_text)

    # Step 6: Clean up
    goal_text = re.sub(r"\s+", " ", goal_text).strip()

    return CraftedGoal(
        goal_text=goal_text,
        services=services,
        risk_level=risk_level,
        risk_reasons=risk_reasons,
        schedule=schedule,
        assumptions=assumptions,
        original_text=original,
        secrets_redacted=secrets_found,
    )


def _strip_recurrence(text: str) -> Tuple[str, Optional[str]]:
    """Remove time/recurrence language from goal. Handle via set_trigger."""
    for pattern in RECURRENCE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            cleaned = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
            return cleaned, match.group(0)
    return text, None


def _strip_secrets(text: str) -> Tuple[str, bool]:
    """Redact any passwords, API keys, tokens from goal text."""
    found = False
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)
            found = True
    return text, found


def _identify_services(text: str, available_tools: List[str]) -> List[str]:
    """Match keywords in goal text to available platform tools."""
    text_lower = text.lower()
    matched = set()
    for keyword, tool_name in SERVICE_KEYWORDS.items():
        if keyword in text_lower and tool_name in available_tools:
            matched.add(tool_name)
    return list(matched)


def _check_scope_risk(text: str) -> Tuple[ScopeRisk, List[str]]:
    """Check for scope risk patterns (twin.md lines 412-428)."""
    reasons = []
    for pattern in HIGH_RISK_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            reasons.append(pattern)
    if reasons:
        return ScopeRisk.HIGH, reasons

    for pattern in MODERATE_RISK_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return ScopeRisk.MODERATE, [pattern]

    return ScopeRisk.SAFE, []


def _apply_defaults(text: str) -> List[str]:
    """Add smart defaults if the goal is missing explicit bounds."""
    assumptions = []
    if not re.search(r"\d+", text):
        assumptions.append("Defaulting to 15 results (no explicit limit found)")
    if not any(w in text.lower() for w in ("save", "store", "email", "send", "write", "database")):
        assumptions.append("Results will be stored in agent database")
    return assumptions


def format_scope_warning(goal: CraftedGoal) -> Optional[dict]:
    """Build scope_warning dict for present_options if risk detected."""
    if goal.risk_level == ScopeRisk.SAFE:
        return None
    return {
        "level": goal.risk_level.value,
        "reasons": goal.risk_reasons,
        "recommendation": (
            "Add explicit bounds (e.g. 'top 10', 'first 50') or sample first"
            if goal.risk_level == ScopeRisk.HIGH
            else "Consider bounding scope or testing with a small sample"
        ),
    }
