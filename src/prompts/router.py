"""PromptRouter — Neural prompt selection using sentence-transformers + MLP.

Architecture (same as RG_Chat's SkillClassifier):
1. Sentence-transformer encodes user message → 384-dim embedding
2. Trained MLP maps embedding → per-module activation probabilities
3. Modules above threshold get injected, capped at max_non_base
4. Base modules (ALWAYS=True) always injected regardless of prediction
5. Active learning: every prediction logged, model retrains on accumulated data
6. Model persisted to disk (data/prompt_classifier.pkl) — survives restarts

This is a MULTI-LABEL classifier — each module is independently scored
(not mutually exclusive like skill classification).
"""
import asyncio
import importlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)

MODEL_NAME = "prompt_classifier"


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


def _load_modules() -> List[PromptModule]:
    """Scan modules/ directory and load all prompt modules."""
    global _ALL_MODULES
    if _ALL_MODULES:
        return _ALL_MODULES

    for fname in sorted(os.listdir(_MODULE_DIR)):
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


def _get_non_base_module_ids() -> List[str]:
    """Get ordered list of non-base module IDs (these are what the classifier predicts)."""
    modules = _load_modules()
    return [m.id for m in modules if not m.always]


# ── Neural Classifier ──

class PromptClassifier:
    """Trained neural prompt selector.

    Uses sentence-transformers for encoding + sklearn MLPClassifier
    for multi-label classification (one binary output per prompt module).
    """

    def __init__(self):
        self._encoder = None
        self._classifiers: Dict[str, Any] = {}  # module_id -> trained classifier
        self._is_trained = False
        self._load_lock = asyncio.Lock()
        self._pending_samples: List[Dict] = []
        self._module_ids: List[str] = []
        self._stats: Dict[str, Any] = {}

    async def ensure_ready(self) -> bool:
        """Load encoder + classifier, training from seed if needed."""
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
                    logger.warning("[PromptRouter] Encoder failed, using fallback")
                    return False

                self._module_ids = _get_non_base_module_ids()

                # Try loading from external DB
                from src.services import ml_model_store as store
                if store.is_available():
                    await store.ensure_tables()
                    saved = await store.load_model(MODEL_NAME)
                    if saved:
                        self._classifiers = saved["model"]["classifiers"]
                        self._stats = saved.get("stats", {})
                        self._is_trained = True
                        logger.info(
                            f"[PromptRouter] Loaded from DB "
                            f"({len(self._classifiers)} classifiers, "
                            f"acc={self._stats.get('mean_accuracy', '?')})"
                        )
                        return True

                # No saved model — train from seed
                logger.info("[PromptRouter] No saved model, training from seed...")
                await self._train_and_save()
                return True

            except Exception as e:
                logger.error(f"[PromptRouter] Init failed: {e}", exc_info=True)
                return False

    def _load_encoder(self) -> bool:
        """Load the sentence-transformer encoder (synchronous)."""
        try:
            from sentence_transformers import SentenceTransformer
            model_name = os.getenv("PROMPT_ROUTER_MODEL", "all-MiniLM-L6-v2")
            logger.info(f"[PromptRouter] Loading encoder: {model_name}")
            self._encoder = SentenceTransformer(model_name)
            return True
        except ImportError:
            logger.warning("[PromptRouter] sentence-transformers not installed")
            return False
        except Exception as e:
            logger.error(f"[PromptRouter] Encoder load error: {e}")
            return False

    def _encode(self, text: str) -> np.ndarray:
        """Encode text to embedding vector."""
        return self._encoder.encode([text], normalize_embeddings=True)[0]

    def _train_on_samples(self, samples: List[Tuple[str, List[str]]]) -> Dict[str, Any]:
        """Train one binary classifier per module (synchronous)."""
        from sklearn.neural_network import MLPClassifier

        logger.info(f"[PromptRouter] Encoding {len(samples)} training samples...")

        # Encode all messages
        X_list = []
        for msg, _ in samples:
            X_list.append(self._encode(msg))
        X = np.array(X_list)

        # Train one binary classifier per non-base module
        classifiers = {}
        accuracies = {}

        for mod_id in self._module_ids:
            # Build binary labels: 1 if module should be injected, 0 otherwise
            y = np.array([1 if mod_id in labels else 0 for _, labels in samples])

            # Skip if all same class (no signal)
            if len(set(y)) < 2:
                logger.info(f"[PromptRouter]   {mod_id}: skipped (all same class)")
                continue

            clf = MLPClassifier(
                hidden_layer_sizes=(128, 64),
                activation="relu",
                solver="adam",
                alpha=0.001,
                max_iter=300,
                early_stopping=True,
                validation_fraction=0.15,
                n_iter_no_change=15,
                random_state=42,
                verbose=False,
            )
            clf.fit(X, y)
            acc = float(clf.score(X, y))
            classifiers[mod_id] = clf
            accuracies[mod_id] = round(acc, 4)
            pos_count = int(y.sum())
            logger.info(f"[PromptRouter]   {mod_id}: accuracy={acc:.3f} "
                        f"(positive={pos_count}/{len(y)})")

        self._classifiers = classifiers
        self._is_trained = True

        mean_acc = np.mean(list(accuracies.values())) if accuracies else 0
        self._stats = {
            "n_samples": len(samples),
            "n_classifiers": len(classifiers),
            "mean_accuracy": round(float(mean_acc), 4),
            "per_module_accuracy": accuracies,
            "timestamp": time.time(),
        }

        logger.info(
            f"[PromptRouter] Training complete: {len(classifiers)} classifiers, "
            f"mean_accuracy={mean_acc:.3f}, samples={len(samples)}"
        )
        return self._stats

    async def _train_and_save(self) -> Dict[str, Any]:
        """Train from seed data + active samples and save to external DB."""
        from src.prompts.training_data import get_training_data
        samples = get_training_data()

        # Load active learning samples from DB
        from src.services import ml_model_store as store
        if store.is_available():
            try:
                active_rows = await store.load_active_samples(MODEL_NAME, min_confidence=0.5)
                for s in active_rows:
                    if s.get("message") and s.get("predicted_modules"):
                        samples.append((s["message"], s["predicted_modules"]))
                if active_rows:
                    logger.info(f"[PromptRouter] Added {len(active_rows)} active samples from DB")
            except Exception as e:
                logger.warning(f"[PromptRouter] Active sample load failed: {e}")

        stats = await asyncio.get_event_loop().run_in_executor(
            None, self._train_on_samples, samples
        )

        # Save to external DB
        if store.is_available():
            await store.save_model(
                MODEL_NAME,
                {"classifiers": self._classifiers},
                self._stats,
            )
        else:
            logger.warning("[PromptRouter] No DATABASE_URL — model NOT persisted")

        return stats

    def predict(self, message: str) -> Dict[str, float]:
        """Predict probability of each module being relevant.

        Returns: {module_id: probability} for all non-base modules.
        """
        emb = self._encode(message)
        emb_2d = emb.reshape(1, -1)

        probs = {}
        for mod_id, clf in self._classifiers.items():
            prob = clf.predict_proba(emb_2d)[0]
            # prob[1] = probability of class 1 (module IS relevant)
            probs[mod_id] = float(prob[1]) if len(prob) > 1 else float(prob[0])

        return probs

    def log_prediction(self, message: str, selected_modules: List[str],
                       confidence: float) -> None:
        """Log prediction for active learning."""
        self._pending_samples.append({
            "message": message[:500],
            "predicted_modules": selected_modules,
            "confidence": round(confidence, 4),
            "timestamp": time.time(),
        })
        # Flush every 50 samples
        if len(self._pending_samples) >= 50:
            self._flush_samples()

    def _flush_samples(self) -> None:
        """Write pending samples to external DB for active learning."""
        if not self._pending_samples:
            return
        samples_to_flush = list(self._pending_samples)
        self._pending_samples.clear()
        # Schedule async DB write
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._flush_samples_async(samples_to_flush))
            else:
                asyncio.run(self._flush_samples_async(samples_to_flush))
        except Exception as e:
            logger.warning(f"[PromptRouter] Sample flush scheduling failed: {e}")

    async def _flush_samples_async(self, samples: List[Dict]) -> None:
        """Async flush to DB."""
        from src.services import ml_model_store as store
        if store.is_available():
            await store.save_active_samples(MODEL_NAME, samples)
            logger.info(f"[PromptRouter] Flushed {len(samples)} active samples to DB")
        else:
            logger.warning("[PromptRouter] No DATABASE_URL — active samples NOT persisted")

    async def retrain(self) -> Dict[str, Any]:
        """Retrain model using seed + all active learning data."""
        self._flush_samples()
        return await self._train_and_save()

    def get_stats(self) -> Dict[str, Any]:
        """Get classifier statistics."""
        return {
            "is_trained": self._is_trained,
            "stats": self._stats,
            "pending_samples": len(self._pending_samples),
            "module_ids": self._module_ids,
        }


# ── Fallback: keyword scoring (used when neural model unavailable) ──

_KEYWORD_MAP = {
    "scrape": ["mood_scraper", "scope_risk"], "crawl": ["mood_scraper", "scope_risk"],
    "research": ["mood_researcher"], "news": ["mood_researcher"],
    "monitor": ["mood_monitor"], "watch": ["mood_monitor"], "alert": ["mood_monitor"],
    "sales": ["mood_sales"], "lead": ["mood_sales"], "prospect": ["mood_sales"],
    "content": ["mood_content"], "write": ["mood_content"], "blog": ["mood_content"],
    "code": ["mood_code"], "github": ["mood_code"],
    "email": ["mood_email"], "send": ["mood_email"],
    "data": ["mood_data"], "spreadsheet": ["mood_data"], "excel": ["mood_data"],
    "social": ["mood_social"], "twitter": ["mood_social"], "reddit": ["mood_social"],
    "api": ["mood_integration"], "connect": ["mood_integration"],
    "build": ["goal_crafting", "dispatching"], "create": ["goal_crafting", "dispatching"],
    "run": ["dispatching"], "delete": ["dispatching"], "stop": ["dispatching"],
    "schedule": ["dispatching"], "modify": ["dispatching"],
    "fix": ["diagnose"], "broken": ["diagnose"], "failing": ["diagnose"],
    "status": ["review"], "list": ["review"], "show": ["review"],
    "all companies": ["scope_risk"], "every": ["scope_risk"],
    "team": ["team_dispatching"], "pipeline": ["team_dispatching"],
    "coordinate": ["team_dispatching"], "workflow": ["team_dispatching"],
    "multiple agents": ["team_dispatching"], "several agents": ["team_dispatching"],
}


def _fallback_select(message: str, mode: str) -> List[str]:
    """Keyword fallback when neural model is unavailable."""
    msg_lower = message.lower()
    scores: Dict[str, float] = {}

    # Mode prompt always included
    if mode in ("brainstorm", "review", "diagnose"):
        scores[mode] = 1.0

    for kw, mods in _KEYWORD_MAP.items():
        if kw in msg_lower:
            for m in mods:
                scores[m] = scores.get(m, 0) + 0.3

    # Build intents get standard modules
    if any(w in msg_lower for w in ("build", "create", "make")):
        for m in ("goal_crafting", "dispatching", "tool_synergies", "models_config", "team_dispatching"):
            scores[m] = scores.get(m, 0) + 0.2

    sorted_mods = sorted(scores.items(), key=lambda x: -x[1])
    return [m for m, s in sorted_mods[:6] if s > 0.1]


# ── Main Router ──

class PromptRouter:
    """Neural prompt selector: picks relevant modules per request."""

    def __init__(self, max_non_base: int = 6):
        self.max_non_base = max_non_base
        self.modules = _load_modules()
        self.classifier = PromptClassifier()
        self._module_map = {m.id: m for m in self.modules}

    async def ensure_ready(self) -> bool:
        """Pre-load the neural classifier."""
        return await self.classifier.ensure_ready()

    def route(
        self,
        mode: str,
        user_message: str,
        context_block: str = "",
        agent_count: int = 0,
        agent_names: Optional[List[str]] = None,
        is_run_event: bool = False,
    ) -> str:
        """Assemble system prompt by selecting relevant modules.

        Uses neural classifier when available, keyword fallback otherwise.
        """
        t0 = time.time()

        # Always-included base modules
        base_modules = [m for m in self.modules if m.always]

        # Select non-base modules
        if self.classifier._is_trained and self.classifier._encoder is not None:
            # ── Neural selection ──
            probs = self.classifier.predict(user_message)

            # Sort by probability, take top-K above threshold
            threshold = 0.3
            scored = sorted(probs.items(), key=lambda x: -x[1])
            selected_ids = [mid for mid, p in scored[:self.max_non_base] if p > threshold]

            # Always include the mode prompt if it exists
            if mode in self._module_map and mode not in selected_ids:
                selected_ids.insert(0, mode)

            # Run events always get run_events prompt
            if is_run_event and "run_events" not in selected_ids:
                selected_ids.append("run_events")

            avg_conf = np.mean([probs.get(m, 0) for m in selected_ids]) if selected_ids else 0
            method = "neural"

            # Log for active learning
            self.classifier.log_prediction(user_message, selected_ids, float(avg_conf))

        else:
            # ── Keyword fallback ──
            selected_ids = _fallback_select(user_message, mode)
            if mode in self._module_map and mode not in selected_ids:
                selected_ids.insert(0, mode)
            if is_run_event and "run_events" not in selected_ids:
                selected_ids.append("run_events")
            avg_conf = 0.0
            method = "fallback"

        # Resolve IDs to actual modules
        selected_modules = []
        for mid in selected_ids[:self.max_non_base]:
            mod = self._module_map.get(mid)
            if mod and not mod.always:
                selected_modules.append(mod)

        latency = (time.time() - t0) * 1000

        logger.info(
            f"[PromptRouter] method={method} mode={mode} "
            f"selected={[m.id for m in selected_modules]} "
            f"conf={avg_conf:.3f} latency={latency:.1f}ms "
            f"msg={user_message[:60]!r}"
        )

        # Assemble prompt
        parts = [m.prompt for m in base_modules]
        parts.extend(m.prompt for m in selected_modules)

        if context_block:
            parts.append(f"<context>\n{context_block}\n</context>")

        if mode == "review" and agent_names:
            parts.append(
                f"<review_context>User has {agent_count} agent(s): "
                f"{', '.join(agent_names)}. Answer directly.</review_context>"
            )

        return "\n\n".join(parts)

    async def retrain(self) -> Dict[str, Any]:
        """Retrain the neural classifier with accumulated data."""
        return await self.classifier.retrain()

    def get_stats(self) -> Dict[str, Any]:
        """Get router statistics."""
        return self.classifier.get_stats()


# ── Singleton ──

_router: Optional[PromptRouter] = None


def get_router() -> PromptRouter:
    """Get or create the global PromptRouter instance."""
    global _router
    if _router is None:
        _router = PromptRouter()
    return _router


async def preload_prompt_router() -> None:
    """Call at app startup to pre-train/load the prompt classifier."""
    t0 = time.time()
    logger.info("[PromptRouter] Preloading at startup...")
    router = get_router()
    ok = await router.ensure_ready()
    elapsed = (time.time() - t0) * 1000
    if ok:
        stats = router.get_stats()
        logger.info(
            f"[PromptRouter] Preload complete in {elapsed:.0f}ms — "
            f"classifiers={stats['stats'].get('n_classifiers', 0)}, "
            f"accuracy={stats['stats'].get('mean_accuracy', 0)}, "
            f"samples={stats['stats'].get('n_samples', 0)}"
        )
    else:
        logger.warning(f"[PromptRouter] Preload FAILED in {elapsed:.0f}ms — using keyword fallback")
