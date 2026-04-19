"""AgentTypeClassifier — Neural model that identifies what type of agent
is being built from the goal + tools, then generates specialised prompts.

Architecture (mirrors SkillClassifier / PromptClassifier):
  sentence-transformers (all-MiniLM-L6-v2)  →  384-dim embedding
  →  MLPClassifier (multi-class, 11 types)
  →  predicted agent_type + confidence

Types: researcher, scraper, monitor, sales, content, code,
       email, data, social, integration, general

Once the type is identified, the SpecialisedPromptWriter assembles
a type-specific BUILDER_SYSTEM prompt using mood knowledge, then the
LLM generates far better instructions than the generic template.

Active learning: every classification is logged. Retrain periodically
to improve accuracy from real-world usage.
"""
import asyncio
import json
import logging
import os
import pickle
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "agent_type_classifier.pkl"
)
ACTIVE_SAMPLES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "agent_type_active_samples.jsonl"
)


class AgentTypeClassifier:
    """Trained neural classifier: goal + tools → agent type."""

    def __init__(self):
        self._encoder = None
        self._classifier = None
        self._label_names: List[str] = []
        self._is_trained = False
        self._load_lock = asyncio.Lock()
        self._pending_samples: List[Dict] = []
        self._stats: Dict[str, Any] = {}

    async def ensure_ready(self) -> bool:
        """Load encoder + classifier. Train from seed if no saved model."""
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

                # Try loading saved model
                if os.path.exists(MODEL_PATH):
                    try:
                        with open(MODEL_PATH, "rb") as f:
                            saved = pickle.load(f)
                        self._classifier = saved["classifier"]
                        self._label_names = saved["label_names"]
                        self._stats = saved.get("stats", {})
                        self._is_trained = True
                        logger.info(
                            f"[AgentTypeClassifier] Loaded from disk — "
                            f"accuracy={self._stats.get('accuracy', '?')}, "
                            f"labels={self._label_names}"
                        )
                        return True
                    except Exception as e:
                        logger.warning(f"[AgentTypeClassifier] Disk load failed: {e}")

                # Train from seed
                logger.info("[AgentTypeClassifier] No saved model, training from seed...")
                await self._train_and_save()
                return True

            except Exception as e:
                logger.error(f"[AgentTypeClassifier] Init failed: {e}", exc_info=True)
                return False

    def _load_encoder(self) -> bool:
        """Load sentence-transformer (synchronous)."""
        try:
            from sentence_transformers import SentenceTransformer
            model_name = os.getenv("PROMPT_ROUTER_MODEL", "all-MiniLM-L6-v2")
            logger.info(f"[AgentTypeClassifier] Loading encoder: {model_name}")
            self._encoder = SentenceTransformer(model_name)
            return True
        except ImportError:
            logger.warning("[AgentTypeClassifier] sentence-transformers not installed")
            return False
        except Exception as e:
            logger.error(f"[AgentTypeClassifier] Encoder error: {e}")
            return False

    def _encode(self, text: str) -> np.ndarray:
        return self._encoder.encode([text], normalize_embeddings=True)[0]

    def _train_on_samples(self, samples: List[Tuple[str, str]]) -> Dict[str, Any]:
        """Train multi-class classifier (synchronous)."""
        from sklearn.neural_network import MLPClassifier
        from sklearn.preprocessing import LabelEncoder

        logger.info(f"[AgentTypeClassifier] Encoding {len(samples)} samples...")

        X = np.array([self._encode(goal) for goal, _ in samples])
        raw_labels = [label for _, label in samples]

        le = LabelEncoder()
        y = le.fit_transform(raw_labels)
        self._label_names = list(le.classes_)

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

        # Per-class accuracy
        from sklearn.metrics import classification_report
        y_pred = clf.predict(X)
        per_class = {}
        for i, name in enumerate(self._label_names):
            mask = y == i
            if mask.sum() > 0:
                per_class[name] = round(float((y_pred[mask] == y[mask]).mean()), 4)

        self._stats = {
            "n_samples": len(samples),
            "n_classes": len(self._label_names),
            "accuracy": round(acc, 4),
            "per_class_accuracy": per_class,
            "label_names": self._label_names,
            "timestamp": time.time(),
        }

        logger.info(
            f"[AgentTypeClassifier] Training complete: "
            f"accuracy={acc:.3f}, classes={len(self._label_names)}, "
            f"samples={len(samples)}"
        )
        return self._stats

    async def _train_and_save(self) -> Dict[str, Any]:
        """Train from seed + active data and persist."""
        from src.builder.agent_type_training_data import get_training_data
        samples = get_training_data()

        # Merge active learning samples
        if os.path.exists(ACTIVE_SAMPLES_PATH):
            try:
                with open(ACTIVE_SAMPLES_PATH, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            s = json.loads(line)
                            if s.get("confidence", 0) > 0.6:
                                samples.append((s["goal"], s["predicted_type"]))
                logger.info(f"[AgentTypeClassifier] Loaded active samples, total={len(samples)}")
            except Exception as e:
                logger.warning(f"[AgentTypeClassifier] Active sample load failed: {e}")

        stats = await asyncio.get_event_loop().run_in_executor(
            None, self._train_on_samples, samples
        )

        # Save
        try:
            os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
            with open(MODEL_PATH, "wb") as f:
                pickle.dump({
                    "classifier": self._classifier,
                    "label_names": self._label_names,
                    "stats": self._stats,
                }, f)
            logger.info(f"[AgentTypeClassifier] Model saved to {MODEL_PATH}")
        except Exception as e:
            logger.warning(f"[AgentTypeClassifier] Save failed: {e}")

        return stats

    def classify(self, goal: str, tools: Optional[List[str]] = None) -> Dict[str, Any]:
        """Classify the agent type from goal + optional tools.

        Returns: {
            "type": "researcher",
            "confidence": 0.92,
            "probabilities": {"researcher": 0.92, "scraper": 0.04, ...}
        }
        """
        if not self._is_trained or self._encoder is None:
            return {"type": "general", "confidence": 0.0, "probabilities": {}}

        # Encode goal text (include tools as context for better classification)
        text = goal
        if tools:
            text += f" (tools: {', '.join(tools)})"
        emb = self._encode(text).reshape(1, -1)

        proba = self._classifier.predict_proba(emb)[0]
        pred_idx = int(np.argmax(proba))
        pred_type = self._label_names[pred_idx]
        confidence = float(proba[pred_idx])

        probabilities = {
            self._label_names[i]: round(float(proba[i]), 4)
            for i in range(len(self._label_names))
        }

        # Log for active learning
        self._pending_samples.append({
            "goal": goal[:500],
            "tools": tools or [],
            "predicted_type": pred_type,
            "confidence": round(confidence, 4),
            "timestamp": time.time(),
        })
        if len(self._pending_samples) >= 50:
            self._flush_samples()

        logger.info(
            f"[AgentTypeClassifier] Classified: {pred_type} "
            f"(conf={confidence:.3f}) for goal={goal[:60]!r}"
        )

        return {
            "type": pred_type,
            "confidence": confidence,
            "probabilities": probabilities,
        }

    def _flush_samples(self):
        if not self._pending_samples:
            return
        try:
            os.makedirs(os.path.dirname(ACTIVE_SAMPLES_PATH), exist_ok=True)
            with open(ACTIVE_SAMPLES_PATH, "a") as f:
                for s in self._pending_samples:
                    f.write(json.dumps(s) + "\n")
        except Exception as e:
            logger.warning(f"[AgentTypeClassifier] Flush failed: {e}")
        self._pending_samples.clear()

    async def retrain(self) -> Dict[str, Any]:
        self._flush_samples()
        return await self._train_and_save()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "is_trained": self._is_trained,
            "stats": self._stats,
            "pending_samples": len(self._pending_samples),
        }


# ── Keyword fallback when neural model unavailable ──

_FALLBACK_KEYWORDS = {
    "researcher": ["research", "investigate", "briefing", "report", "analyze market", "news", "summarize papers"],
    "scraper": ["scrape", "crawl", "extract", "collect from", "listings"],
    "monitor": ["monitor", "watch", "alert", "track", "notify when", "detect changes"],
    "sales": ["lead", "prospect", "outreach", "CRM", "sales", "contact info", "decision maker"],
    "content": ["write", "blog", "newsletter", "content", "article", "copy", "SEO", "press release"],
    "code": ["code", "script", "debug", "test", "refactor", "CI/CD", "pull request", "github"],
    "email": ["email", "inbox", "gmail", "send email", "newsletter email", "digest"],
    "data": ["data", "CSV", "spreadsheet", "analytics", "dashboard", "metrics", "statistics"],
    "social": ["twitter", "reddit", "linkedin", "instagram", "social media", "post to"],
    "integration": ["connect", "integrate", "sync", "webhook", "API bridge", "automate workflow", "Slack bot"],
}


def fallback_classify(goal: str) -> str:
    """Keyword-based fallback classification."""
    goal_lower = goal.lower()
    scores = {}
    for agent_type, keywords in _FALLBACK_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in goal_lower:
                scores[agent_type] = scores.get(agent_type, 0) + 1
    if scores:
        return max(scores, key=scores.get)
    return "general"


# ── Singleton ──

_classifier: Optional[AgentTypeClassifier] = None


def get_agent_type_classifier() -> AgentTypeClassifier:
    global _classifier
    if _classifier is None:
        _classifier = AgentTypeClassifier()
    return _classifier


async def preload_agent_type_classifier() -> None:
    """Call at startup to pre-train/load."""
    t0 = time.time()
    logger.info("[AgentTypeClassifier] Preloading...")
    clf = get_agent_type_classifier()
    ok = await clf.ensure_ready()
    elapsed = (time.time() - t0) * 1000
    if ok:
        stats = clf.get_stats()
        logger.info(
            f"[AgentTypeClassifier] Ready in {elapsed:.0f}ms — "
            f"accuracy={stats['stats'].get('accuracy', 0)}, "
            f"classes={stats['stats'].get('n_classes', 0)}"
        )
    else:
        logger.warning(f"[AgentTypeClassifier] FAILED in {elapsed:.0f}ms — using keyword fallback")
