"""Dual Hash Sphere Memory — user+agent sphere + RAG learning via memory_service"""
import logging
from typing import Any, Dict, List

import httpx

from src.core.config import MEMORY_SERVICE_URL

logger = logging.getLogger(__name__)


class MemoryStore:
    def __init__(self, workspace_id: str, agent_id: str = ""):
        self.workspace_id = workspace_id
        self.agent_id = agent_id
        self.base = MEMORY_SERVICE_URL

    # ── User Memory (Hash Sphere — user level) ──

    async def get_user_memory(self) -> Dict[str, Any]:
        """Get user-level hash sphere memory."""
        result = await self._post("/memory/hash-sphere/search", {
            "query": "user preferences and facts",
            "user_id": self.workspace_id,
            "scope": "user",
            "limit": 20,
        })
        return result or {}

    async def update_user_memory(self, content: str) -> Dict:
        """Store fact in user hash sphere."""
        return await self._post("/rag/memories", {
            "content": content,
            "user_id": self.workspace_id,
            "scope": "user",
            "type": "fact",
        })

    # ── Agent Memory (Hash Sphere — agent level) ──

    async def get_agent_memory(self) -> Dict[str, Any]:
        """Get agent-specific hash sphere memory."""
        if not self.agent_id:
            return {}
        result = await self._post("/memory/hash-sphere/search", {
            "query": "agent learnings and context",
            "agent_id": self.agent_id,
            "user_id": self.workspace_id,
            "scope": "agent",
            "limit": 20,
        })
        return result or {}

    async def store_agent_learning(self, content: str, run_id: str = "") -> Dict:
        """Store learning from a run in agent hash sphere."""
        if not self.agent_id:
            return {"error": "No agent_id"}
        return await self._post("/rag/memories", {
            "content": content,
            "user_id": self.workspace_id,
            "agent_id": self.agent_id,
            "scope": "agent",
            "type": "learning",
            "metadata": {"run_id": run_id},
        })

    # ── Dual Memory (user + agent combined) ──

    async def get_dual_memory(self) -> Dict[str, Any]:
        """Get both user and agent memory combined."""
        user_mem = await self.get_user_memory()
        agent_mem = await self.get_agent_memory() if self.agent_id else {}
        return {"user_memory": user_mem, "agent_memory": agent_mem}

    # ── RAG Learning ──

    async def ask_memory(self, question: str) -> Dict:
        """Ask RAG memory a question — agent learns from past context."""
        body = {"query": question, "user_id": self.workspace_id}
        if self.agent_id:
            body["agent_id"] = self.agent_id
        return await self._post("/rag/ask", body)

    async def store_run_summary(self, summary: str, run_id: str, agent_id: str = "") -> Dict:
        """Store run summary as a learning for future runs."""
        return await self._post("/rag/memories", {
            "content": f"Run result: {summary}",
            "user_id": self.workspace_id,
            "agent_id": agent_id or self.agent_id,
            "scope": "agent",
            "type": "run_summary",
            "metadata": {"run_id": run_id},
        })

    # ── Hash Sphere Operations ──

    async def create_hash_sphere_anchor(self, content: str, anchor_type: str = "fact") -> Dict:
        """Create anchor in hash sphere."""
        return await self._post("/memory/hash-sphere/anchors", {
            "content": content,
            "user_id": self.workspace_id,
            "agent_id": self.agent_id,
            "type": anchor_type,
        })

    async def get_hash_sphere_anchors(self) -> Dict:
        """Get all hash sphere anchors."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{self.base}/memory/hash-sphere/anchors",
                                params={"user_id": self.workspace_id})
                if r.status_code == 200:
                    return r.json()
        except Exception as e:
            logger.warning(f"[Memory] get anchors failed: {e}")
        return {}

    # ── Architect Self-Learning (learns from every conversation) ──

    async def store_architect_insight(self, insight: str, category: str = "observation") -> Dict:
        """Store an insight the architect learned during conversation.

        Categories: observation, user_preference, agent_pattern, failure_pattern, success_pattern
        This makes the architect smarter over time — it remembers what works.
        """
        return await self._post("/rag/memories", {
            "content": f"[architect:{category}] {insight}",
            "user_id": self.workspace_id,
            "scope": "user",
            "type": "architect_insight",
            "metadata": {"category": category, "source": "architect"},
        })

    async def retrieve_architect_context(self) -> Dict[str, Any]:
        """Pull all relevant context for the architect at session start.

        Combines: user preferences, past architect insights, agent patterns.
        This is what makes the architect a real agent — it remembers and learns.
        """
        user_mem = await self.get_user_memory()
        insights = await self._post("/memory/hash-sphere/search", {
            "query": "architect insights patterns preferences",
            "user_id": self.workspace_id,
            "scope": "user",
            "limit": 15,
        })
        return {
            "user_memory": user_mem,
            "architect_insights": insights,
        }

    # ── Internal HTTP helper ──

    async def _post(self, path: str, body: Dict) -> Dict:
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(f"{self.base}{path}", json=body)
                if r.status_code == 200:
                    return r.json()
                logger.warning(f"[Memory] {path} → {r.status_code}")
        except Exception as e:
            logger.warning(f"[Memory] {path} failed: {e}")
        return {}
