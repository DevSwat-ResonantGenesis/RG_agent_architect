"""Architect Neural Tool Classifier — decides which tool GROUP to inject per message.

Instead of sending all 53 tool definitions to the LLM (3000+ tokens), this
classifier predicts which group of tools the user needs and only injects those.

Architecture (same as Chat's ToolClassifier):
  sentence-transformers (all-MiniLM-L6-v2) → 384-dim embedding
  → MLPClassifier → predicted tool_group + confidence
  → map group → subset of ORCHESTRATOR_TOOLS

Groups:
  build     → build_agent, modify_agent, continue_build, message_build,
              list_engine_tools, execute_tool, predict_tools, update_agent_config,
              update_agent_prompt, get_agent_prompt, check_integrations
  run       → run_agent, stop_run, cancel_session, emergency_stop,
              approve_step, get_pending_approvals
  schedule  → create_schedule, set_trigger, list_schedules, update_schedule,
              delete_schedule
  inspect   → workspace_snapshot, agent_snapshot, run_snapshot, get_agent_sessions,
              get_session_steps, get_agent_metrics, list_providers, list_engine_tools
  memory    → get_user_memory, update_user_memory, get_agent_memory,
              get_dual_memory, ask_memory, store_insight, retrieve_architect_context
  plan      → create_task, list_tasks, update_task, brainstorm, get_workspace_plan
  delegate  → delegate_to_agent, delegate_by_name, run_agent
  workspace → set_workspace_name, list_workspace_databases, list_workspace_tools,
              get_credits_info, check_credits, check_integrations,
              get_current_time, delete_agent, delete_all_agents
  none      → no tools needed, pure text response
"""
import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Tool group → list of orchestrator tool names to inject
TOOL_GROUPS: Dict[str, List[str]] = {
    "build": [
        "build_agent", "modify_agent", "continue_build", "message_build",
        "list_engine_tools", "execute_tool", "update_agent_config",
        "update_agent_prompt", "get_agent_prompt", "check_integrations",
        "check_credits", "workspace_snapshot", "present_options",
    ],
    "run": [
        "run_agent", "stop_run", "cancel_session", "emergency_stop",
        "approve_step", "get_pending_approvals", "workspace_snapshot",
        "get_agent_sessions",
    ],
    "schedule": [
        "create_schedule", "set_trigger", "list_schedules",
        "workspace_snapshot", "present_options",
    ],
    "inspect": [
        "workspace_snapshot", "agent_snapshot", "run_snapshot",
        "get_agent_sessions", "get_session_steps", "get_agent_metrics",
        "list_providers", "list_engine_tools",
    ],
    "memory": [
        "get_user_memory", "update_user_memory", "get_agent_memory",
        "get_dual_memory", "ask_memory", "store_insight",
        "retrieve_architect_context",
    ],
    "plan": [
        "create_task", "list_tasks", "update_task", "brainstorm",
        "get_workspace_plan",
    ],
    "delegate": [
        "delegate_to_agent", "delegate_by_name", "run_agent",
        "workspace_snapshot",
    ],
    "workspace": [
        "set_workspace_name", "list_workspace_databases", "list_workspace_tools",
        "get_credits_info", "check_credits", "check_integrations",
        "get_current_time", "delete_agent", "delete_all_agents",
        "workspace_snapshot", "present_options",
    ],
}

# All group labels (including "none" for general chat)
ALL_GROUPS = list(TOOL_GROUPS.keys()) + ["none"]
GROUP_TO_IDX = {g: i for i, g in enumerate(ALL_GROUPS)}
IDX_TO_GROUP = {i: g for i, g in enumerate(ALL_GROUPS)}


class ArchitectToolClassifier:
    """Neural classifier: user message → tool group → subset of tools."""

    def __init__(self):
        self._encoder = None
        self._classifier = None
        self._is_trained = False
        self._load_lock = asyncio.Lock()
        self._stats: Dict[str, Any] = {}

    async def ensure_ready(self) -> bool:
        if self._is_trained and self._encoder is not None:
            return True
        async with self._load_lock:
            if self._is_trained and self._encoder is not None:
                return True
            try:
                ok = await asyncio.get_event_loop().run_in_executor(
                    None, self._load_encoder
                )
                if not ok:
                    return False
                await asyncio.get_event_loop().run_in_executor(
                    None, self._train_from_seed
                )
                return True
            except Exception as e:
                logger.error(f"[ArchitectToolClassifier] Init failed: {e}", exc_info=True)
                return False

    def _load_encoder(self) -> bool:
        try:
            from sentence_transformers import SentenceTransformer
            model_name = os.getenv("PROMPT_ROUTER_MODEL", "all-MiniLM-L6-v2")
            logger.info(f"[ArchitectToolClassifier] Loading encoder: {model_name}")
            self._encoder = SentenceTransformer(model_name)
            return True
        except ImportError:
            logger.warning("[ArchitectToolClassifier] sentence-transformers not installed")
            return False
        except Exception as e:
            logger.error(f"[ArchitectToolClassifier] Encoder error: {e}")
            return False

    def _encode(self, text: str) -> np.ndarray:
        return self._encoder.encode([text], normalize_embeddings=True)[0]

    def _train_from_seed(self) -> None:
        from sklearn.neural_network import MLPClassifier
        from src.orchestrator.tool_training_data import get_training_data

        samples = get_training_data()
        logger.info(f"[ArchitectToolClassifier] Training on {len(samples)} samples...")

        X = np.array([self._encode(msg) for msg, _ in samples])
        y = np.array([GROUP_TO_IDX[group] for _, group in samples])

        clf = MLPClassifier(
            hidden_layer_sizes=(128, 64),
            activation="relu",
            solver="adam",
            alpha=0.001,
            max_iter=400,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=20,
            random_state=42,
            verbose=False,
        )
        clf.fit(X, y)
        acc = float(clf.score(X, y))

        self._classifier = clf
        self._is_trained = True
        self._stats = {
            "n_samples": len(samples),
            "n_groups": len(ALL_GROUPS),
            "accuracy": round(acc, 4),
            "timestamp": time.time(),
        }
        logger.info(
            f"[ArchitectToolClassifier] Trained: accuracy={acc:.3f}, "
            f"groups={len(ALL_GROUPS)}, samples={len(samples)}"
        )

    def predict(self, message: str) -> Tuple[str, float, Dict[str, float]]:
        """Predict tool group for a user message.

        Returns: (group_name, confidence, probabilities)
        """
        if not self._is_trained or self._encoder is None:
            return "build", 0.0, {}

        emb = self._encode(message).reshape(1, -1)
        proba = self._classifier.predict_proba(emb)[0]
        pred_idx = int(np.argmax(proba))
        group = IDX_TO_GROUP[pred_idx]
        confidence = float(proba[pred_idx])

        probabilities = {
            IDX_TO_GROUP[i]: round(float(proba[i]), 4)
            for i in range(len(proba))
        }

        logger.info(
            f"[ArchitectToolClassifier] group={group} conf={confidence:.3f} "
            f"msg={message[:60]!r}"
        )
        return group, confidence, probabilities

    def get_tools_for_message(self, message: str) -> Tuple[List[str], str]:
        """Get the relevant tool NAMES for a user message.

        Returns: (list_of_tool_names, predicted_group)
        If group is "none", returns empty list (no tools needed).
        For low confidence, merges top-2 groups for safety.
        """
        group, confidence, probs = self.predict(message)

        if group == "none" and confidence > 0.5:
            return [], "none"

        tool_names: Set[str] = set()

        # Primary group
        if group in TOOL_GROUPS:
            tool_names.update(TOOL_GROUPS[group])

        # Low confidence → merge second-best group
        if confidence < 0.5:
            sorted_groups = sorted(probs.items(), key=lambda x: -x[1])
            for g, _ in sorted_groups[:2]:
                if g != "none" and g in TOOL_GROUPS:
                    tool_names.update(TOOL_GROUPS[g])

        # Always include these universal tools
        tool_names.add("workspace_snapshot")
        tool_names.add("present_options")
        tool_names.add("get_current_time")

        return list(tool_names), group

    def get_stats(self) -> Dict[str, Any]:
        return {
            "is_trained": self._is_trained,
            "stats": self._stats,
        }


# ── Keyword fallback when neural model unavailable ──

_FALLBACK_KEYWORDS = {
    "build": ["create", "build", "make", "new agent", "modify", "add tool", "remove tool", "change model", "update prompt", "improve"],
    "run": ["run", "execute", "start", "stop", "cancel", "kill", "emergency", "halt", "abort", "approve", "reject"],
    "schedule": ["schedule", "cron", "daily", "hourly", "weekly", "trigger", "recurring", "automation"],
    "inspect": ["show", "list", "agents", "sessions", "steps", "metrics", "performance", "provider", "history", "trace", "versions"],
    "memory": ["remember", "memory", "recall", "learned", "insight", "knowledge", "context"],
    "plan": ["task", "todo", "plan", "brainstorm", "idea", "priority"],
    "delegate": ["delegate", "ask my", "use my", "chain", "tell my agent"],
    "workspace": ["credit", "billing", "integration", "connected", "workspace", "rename", "delete all", "clean up", "time"],
}


def fallback_get_tools(message: str) -> Tuple[List[str], str]:
    """Keyword-based fallback when neural classifier unavailable."""
    msg_lower = message.lower()
    scores: Dict[str, int] = {}
    for group, keywords in _FALLBACK_KEYWORDS.items():
        for kw in keywords:
            if kw in msg_lower:
                scores[group] = scores.get(group, 0) + 1

    if not scores:
        return list(TOOL_GROUPS.get("build", [])), "build"

    best_group = max(scores, key=scores.get)
    if best_group == "none":
        return [], "none"

    tool_names = set(TOOL_GROUPS.get(best_group, []))
    tool_names.add("workspace_snapshot")
    tool_names.add("present_options")
    tool_names.add("get_current_time")
    return list(tool_names), best_group


# Singleton
architect_tool_classifier = ArchitectToolClassifier()
