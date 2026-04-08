"""Goal Crafting Pipeline — 8-step goal validation and composition"""
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
    goal_text: str
    services: List[str]
    risk_level: ScopeRisk
    risk_reasons: List[str] = field(default_factory=list)
    schedule: Optional[str] = None
    assumptions: List[str] = field(default_factory=list)

HIGH_RISK = [r"all\s+(companies|businesses|restaurants)\s+in", r"scrape\s+all", r"across\s+all"]
MOD_RISK = [r"companies?\s+in\s+\w+\s+without", r"check\s+each\s+website"]
RECURRENCE = [r"every\s+(day|hour|week|month)", r"daily", r"weekly", r"hourly"]


def craft_goal(raw: str, tools: List[str]) -> CraftedGoal:
    goal, sched = _strip_recurrence(raw)
    goal = _strip_secrets(goal)
    services = _identify_services(goal, tools)
    risk, reasons = _check_risk(goal)
    assumptions = ["Defaulting to 15 results"] if not re.search(r"\d+", goal) else []
    return CraftedGoal(goal, services, risk, reasons, sched, assumptions)


def _strip_recurrence(text: str) -> Tuple[str, Optional[str]]:
    for p in RECURRENCE:
        m = re.search(p, text, re.I)
        if m:
            return re.sub(p, "", text, flags=re.I).strip(), m.group(0)
    return text, None

def _strip_secrets(text: str) -> str:
    return re.sub(r"(password|api_?key|token|secret)\s*[:=]\s*\S+", "[REDACTED]", text, flags=re.I)

def _identify_services(text: str, tools: List[str]) -> List[str]:
    kw = {"search":"web_search","scrape":"scrape_page","email":"send_email",
           "chart":"build_chart","sheet":"google_sheets","linkedin":"scrape_platforms",
           "research":"deep_research","stock":"stock_market_data","slide":"create_presentation",
           "image":"generate_media","video":"generate_media","doc":"documents"}
    return list({kw[k] for k in kw if k in text.lower() and kw[k] in tools})

def _check_risk(text: str) -> Tuple[ScopeRisk, List[str]]:
    for p in HIGH_RISK:
        if re.search(p, text, re.I): return ScopeRisk.HIGH, [p]
    for p in MOD_RISK:
        if re.search(p, text, re.I): return ScopeRisk.MODERATE, [p]
    return ScopeRisk.SAFE, []
