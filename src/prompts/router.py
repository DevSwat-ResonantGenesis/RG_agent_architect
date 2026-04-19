"""PromptRouter — Smart prompt selection using embeddings + tag scoring.

Architecture:
1. Each prompt module has an ID, TAGS, ALWAYS flag, and PROMPT text.
2. At startup, all modules are loaded and their TAGS are indexed.
3. For each request, the router:
   a. Always includes base prompts (ALWAYS=True)
   b. Includes mode-specific prompt based on classified mode
   c. Scores remaining prompts by tag relevance + embedding similarity
   d. Picks top-K most relevant prompts to inject
4. Result: small, focused system prompt with only what's needed.

This avoids injecting all 20+ prompts (noise) while ensuring the LLM
gets the exact guidance it needs for the current request.
"""
import importlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── Prompt Module Definition ──

@dataclass
class PromptModule:
    id: str
    tags: List[str]
    always: bool
    prompt: str


# ── Load all modules from the modules/ directory ──

_MODULE_DIR = os.path.join(os.path.dirname(__file__), "modules")
_ALL_MODULES: List[PromptModule] = []


def _load_modules():
    """Scan modules/ directory and load all prompt modules."""
    global _ALL_MODULES
    if _ALL_MODULES:
        return _ALL_MODULES

    modules_dir = _MODULE_DIR
    for fname in sorted(os.listdir(modules_dir)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        mod_name = fname[:-3]
        try:
            mod = importlib.import_module(f"src.prompts.modules.{mod_name}")
            if hasattr(mod, "PROMPT") and hasattr(mod, "ID"):
                _ALL_MODULES.append(PromptModule(
                    id=getattr(mod, "ID"),
                    tags=getattr(mod, "TAGS", []),
                    always=getattr(mod, "ALWAYS", False),
                    prompt=getattr(mod, "PROMPT"),
                ))
        except Exception as e:
            logger.warning(f"Failed to load prompt module {mod_name}: {e}")

    logger.info(f"[PromptRouter] Loaded {len(_ALL_MODULES)} prompt modules: "
                f"{[m.id for m in _ALL_MODULES]}")
    return _ALL_MODULES


# ── Keyword extraction for tag matching ──

# Map common user intent keywords to prompt tags
_INTENT_TAG_MAP = {
    # Build intents
    "build": ["build", "control"],
    "create": ["build", "control"],
    "make": ["build", "control"],
    "agent": ["build", "control"],
    # Mood detection keywords
    "scrape": ["scraping", "data", "mood"],
    "scraper": ["scraping", "data", "mood"],
    "crawl": ["scraping", "data", "mood"],
    "research": ["research", "mood"],
    "news": ["research", "mood"],
    "briefing": ["research", "mood"],
    "monitor": ["monitoring", "alerts", "mood"],
    "watch": ["monitoring", "alerts", "mood"],
    "alert": ["monitoring", "alerts", "mood"],
    "track": ["monitoring", "mood"],
    "sales": ["sales", "leads", "mood"],
    "lead": ["sales", "leads", "mood"],
    "prospect": ["sales", "leads", "mood"],
    "outreach": ["sales", "outreach", "mood"],
    "crm": ["sales", "crm", "mood"],
    "email": ["email", "communication", "mood"],
    "send": ["email", "communication"],
    "content": ["content", "writing", "mood"],
    "write": ["content", "writing", "mood"],
    "blog": ["content", "writing", "mood"],
    "newsletter": ["content", "newsletter", "mood"],
    "social": ["social", "mood"],
    "twitter": ["social", "mood"],
    "reddit": ["social", "community", "mood"],
    "linkedin": ["social", "mood"],
    "code": ["code", "development", "mood"],
    "github": ["code", "development", "mood"],
    "programming": ["code", "development", "mood"],
    "data": ["data", "analysis", "mood"],
    "spreadsheet": ["data", "spreadsheet", "mood"],
    "excel": ["data", "spreadsheet", "mood"],
    "csv": ["data", "mood"],
    "analyze": ["data", "analysis", "mood"],
    "api": ["integration", "api", "mood"],
    "integrate": ["integration", "mood"],
    "connect": ["integration", "mood"],
    "automate": ["automation", "integration", "mood"],
    "workflow": ["automation", "integration", "mood"],
    # Mode keywords
    "fix": ["diagnose"],
    "broken": ["diagnose"],
    "failing": ["diagnose"],
    "debug": ["diagnose"],
    "status": ["review"],
    "history": ["review"],
    "results": ["review"],
    "credits": ["review"],
    "list": ["review"],
    "show": ["review"],
    # Event keywords
    "run event": ["event", "lifecycle"],
    "completed": ["event", "lifecycle"],
    "success": ["event", "lifecycle"],
    "failed": ["event", "lifecycle"],
    # Config keywords
    "model": ["config"],
    "loops": ["config"],
    "temperature": ["config"],
    "tools": ["tools", "config"],
    "schedule": ["lifecycle"],
    "trigger": ["lifecycle"],
}


def _extract_tags_from_message(message: str) -> Set[str]:
    """Extract relevant prompt tags from user message keywords."""
    msg_lower = message.lower()
    tags = set()
    for keyword, ktags in _INTENT_TAG_MAP.items():
        if keyword in msg_lower:
            tags.update(ktags)
    return tags


def _score_module(module: PromptModule, mode: str, message_tags: Set[str]) -> float:
    """Score how relevant a prompt module is for the current request.

    Returns 0.0-1.0. Higher = more relevant.
    """
    if module.always:
        return 1.0  # base prompts always included

    score = 0.0

    # Mode match (high weight)
    if mode in module.tags:
        score += 0.6

    # Tag overlap with message intent
    tag_set = set(module.tags)
    overlap = tag_set & message_tags
    if overlap:
        score += 0.3 * (len(overlap) / max(len(tag_set), 1))

    # Mood prompts get a boost if any mood tag matched
    if "mood" in module.tags and "mood" in message_tags:
        mood_specific_tags = tag_set - {"mood", "build"}
        mood_overlap = mood_specific_tags & message_tags
        if mood_overlap:
            score += 0.3  # Strong match: specific mood keywords found

    return min(score, 1.0)


# ── Main Router ──

class PromptRouter:
    """Selects and assembles the right prompt modules for each request."""

    def __init__(self, max_non_base: int = 6):
        """
        Args:
            max_non_base: Maximum number of non-base prompts to inject.
                         Keeps the system prompt focused and small.
        """
        self.max_non_base = max_non_base
        self.modules = _load_modules()

    def route(
        self,
        mode: str,
        user_message: str,
        context_block: str = "",
        agent_count: int = 0,
        agent_names: Optional[List[str]] = None,
        is_run_event: bool = False,
    ) -> str:
        """Assemble the system prompt by selecting relevant modules.

        Args:
            mode: classified mode (brainstorm, control, review, diagnose)
            user_message: the user's current message
            context_block: workspace context string
            agent_count: number of agents in workspace
            agent_names: list of agent names
            is_run_event: whether this is a run event notification

        Returns:
            Assembled system prompt string
        """
        message_tags = _extract_tags_from_message(user_message)

        # Add mode as a tag
        message_tags.add(mode)

        # If run event, add event tags
        if is_run_event:
            message_tags.add("event")
            message_tags.add("lifecycle")

        # Score all modules
        scored: List[Tuple[float, PromptModule]] = []
        base_modules: List[PromptModule] = []

        for mod in self.modules:
            if mod.always:
                base_modules.append(mod)
            else:
                score = _score_module(mod, mode, message_tags)
                if score > 0.1:  # threshold: skip irrelevant modules
                    scored.append((score, mod))

        # Sort by score descending, take top-K
        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [mod for _, mod in scored[:self.max_non_base]]

        # Log what was selected for debugging
        selected_ids = [m.id for m in selected]
        logger.info(f"[PromptRouter] mode={mode}, tags={message_tags}, "
                     f"selected={[m.id for m in base_modules] + selected_ids}")

        # Assemble
        parts = [m.prompt for m in base_modules]
        parts.extend(m.prompt for m in selected)

        # Inject workspace context
        if context_block:
            parts.append(f"<context>\n{context_block}\n</context>")

        # Review mode: inject agent list
        if mode == "review" and agent_names:
            parts.append(
                f"<review_context>User has {agent_count} agent(s): "
                f"{', '.join(agent_names)}. Answer directly.</review_context>"
            )

        return "\n\n".join(parts)


# ── Singleton instance ──

_router: Optional[PromptRouter] = None


def get_router() -> PromptRouter:
    """Get or create the global PromptRouter instance."""
    global _router
    if _router is None:
        _router = PromptRouter()
    return _router
