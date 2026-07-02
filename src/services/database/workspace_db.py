"""Workspace DB — Agent Engine API client (no separate DB, uses same store as all agents)"""
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.core.config import AGENT_ENGINE_URL

logger = logging.getLogger(__name__)


class WorkspaceDB:
    """Talks to the Agent Engine API for all agent CRUD — same DB as every other agent.

    Per-user isolation via x-user-id header. No separate architect_* tables.
    """

    def __init__(self, workspace_id: str, is_superuser: bool = False,
                 unlimited_credits: bool = False, user_role: str = "user"):
        self.workspace_id = workspace_id
        self._headers = {
            "x-user-id": workspace_id,
            "Content-Type": "application/json",
            "x-is-superuser": "true" if is_superuser else "false",
            "x-unlimited-credits": "true" if unlimited_credits else "false",
            "x-user-role": user_role,
        }

    async def get_snapshot(self) -> Dict:
        """List all agents for this user from Agent Engine."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{AGENT_ENGINE_URL}/agents/",
                    headers=self._headers,
                )
                if resp.status_code != 200:
                    logger.warning(f"[WorkspaceDB] list agents failed: {resp.status_code}")
                    return {"agents": [], "agent_count": 0}
                agents = resp.json()
                # Normalize to list if API returns dict wrapper
                if isinstance(agents, dict):
                    agents = agents.get("agents", [])
                return {"agents": agents, "agent_count": len(agents)}
        except Exception as e:
            logger.error(f"[WorkspaceDB] get_snapshot error: {e}")
            return {"agents": [], "agent_count": 0}

    async def save_agent(self, agent_id: str, name: str, goal: str, icon: str = "🤖",
                         system_prompt: str = "", tools: list = None, needs_build: bool = True,
                         max_loops: int = 30, temperature: float = 0.5,
                         model: str = "llama-3.3-70b-versatile",
                         provider_is_temporary: bool = False,
                         provider_temporary_reason: Optional[str] = None,
                         ideal_provider: Optional[str] = None) -> Dict:
        """Create or update an agent via Agent Engine API.

        New agents are saved as status="draft" — NOT immediately active/live
        — until the build pipeline's verification checklist passes and
        activate_agent() is called. This is the sandbox-gating point: a
        broken agent never gets full platform access (DSID registration)
        just for having been saved.
        """
        provider = model.split("/")[0] if "/" in model else ""
        model_name = model.split("/", 1)[1] if "/" in model else model
        payload = {
            "name": name,
            "description": goal,
            "goal": goal,
            "system_prompt": system_prompt or f"You are {name}. {goal}",
            "provider": provider,
            "model": model_name,
            "temperature": temperature,
            "max_tokens": 128000,
            "tools": tools or [],
            "safety_config": {"max_loops": max_loops, "max_tokens_per_run": 500000},
            "is_active": True,
            "status": "draft",
            "provider_is_temporary": provider_is_temporary,
            "provider_temporary_reason": provider_temporary_reason,
            "ideal_provider": ideal_provider,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Try PATCH first (update existing) — don't reset status/DSID
                # state on a plain update of an already-live agent.
                update_payload = {k: v for k, v in payload.items() if k != "status"}
                resp = await client.patch(
                    f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                    headers=self._headers, json=update_payload,
                )
                if resp.status_code == 200:
                    return {"agent_id": agent_id, "saved": True, "action": "updated"}
                # If not found, create new
                resp = await client.post(
                    f"{AGENT_ENGINE_URL}/agents/",
                    headers=self._headers, json=payload,
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return {"agent_id": data.get("id", agent_id), "saved": True, "action": "created"}
                logger.warning(f"[WorkspaceDB] save_agent failed: {resp.status_code} {resp.text[:200]}")
                return {"agent_id": agent_id, "saved": False, "error": resp.text[:200]}
        except Exception as e:
            logger.error(f"[WorkspaceDB] save_agent error: {e}")
            return {"agent_id": agent_id, "saved": False, "error": str(e)}

    async def activate_agent(self, agent_id: str) -> Dict:
        """Transition an agent from draft/verifying to active — the
        sandbox-gated go-live point. Only call this after the build
        pipeline's verification checklist has actually passed."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.patch(
                    f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                    headers=self._headers, json={"status": "active"},
                )
                if resp.status_code == 200:
                    return {"agent_id": agent_id, "activated": True}
                logger.warning(f"[WorkspaceDB] activate_agent failed: {resp.status_code} {resp.text[:200]}")
                return {"agent_id": agent_id, "activated": False, "error": resp.text[:200]}
        except Exception as e:
            logger.error(f"[WorkspaceDB] activate_agent error: {e}")
            return {"agent_id": agent_id, "activated": False, "error": str(e)}

    async def mark_needs_attention(self, agent_id: str, reason: str) -> Dict:
        """Leave an agent visibly flagged as needing attention (verification
        failed after bounded retries) instead of silently active or hidden."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.patch(
                    f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                    headers=self._headers,
                    json={"status": "needs_attention", "provider_temporary_reason": reason[:2000]},
                )
                if resp.status_code == 200:
                    return {"agent_id": agent_id, "marked": True}
                logger.warning(f"[WorkspaceDB] mark_needs_attention failed: {resp.status_code} {resp.text[:200]}")
                return {"agent_id": agent_id, "marked": False, "error": resp.text[:200]}
        except Exception as e:
            logger.error(f"[WorkspaceDB] mark_needs_attention error: {e}")
            return {"agent_id": agent_id, "marked": False, "error": str(e)}

    async def get_agent(self, agent_id: str) -> Optional[Dict]:
        """Get a single agent by ID from Agent Engine."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                    headers=self._headers,
                )
                if resp.status_code != 200:
                    return None
                return resp.json()
        except Exception as e:
            logger.error(f"[WorkspaceDB] get_agent error: {e}")
            return None

    async def get_agent_snapshot(self, agent_id: str) -> Dict:
        """Get agent details + recent sessions from Agent Engine."""
        agent = await self.get_agent(agent_id)
        if not agent:
            return {"error": "Not found"}
        sessions = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{AGENT_ENGINE_URL}/agents/{agent_id}/sessions",
                    headers=self._headers,
                )
                if resp.status_code == 200:
                    sessions = resp.json()
                    if isinstance(sessions, dict):
                        sessions = sessions.get("sessions", [])
        except Exception as e:
            logger.warning(f"[WorkspaceDB] sessions fetch failed: {e}")
        return {"agent": agent, "recent_runs": sessions[:10]}

    async def get_run_snapshot(self, run_id: str) -> Dict:
        """Get session/run details from Agent Engine."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{AGENT_ENGINE_URL}/agents/sessions/{run_id}",
                    headers=self._headers,
                )
                if resp.status_code != 200:
                    return {"error": "Not found"}
                return resp.json()
        except Exception as e:
            logger.error(f"[WorkspaceDB] get_run_snapshot error: {e}")
            return {"error": str(e)}

    async def delete_agent(self, agent_id: str) -> Dict:
        """Archive agent via Agent Engine API."""
        print(f"[DELETE_AGENT] Deleting {agent_id} with headers x-user-id={self._headers.get('x-user-id')}", flush=True)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.delete(
                    f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                    headers=self._headers,
                )
                if resp.status_code in (200, 204):
                    try:
                        body = resp.json()
                        return {**body, "deleted": agent_id}
                    except Exception:
                        return {"deleted": agent_id, "status": "archived"}
                elif resp.status_code == 404:
                    return {"error": "Agent not found"}
                else:
                    return {"error": f"Delete failed: HTTP {resp.status_code} - {resp.text[:200]}"}
        except Exception as e:
            logger.error(f"[WorkspaceDB] delete_agent error: {e}")
            return {"error": str(e)}

    async def delete_all_agents(self) -> Dict:
        """Delete ALL agents in workspace by listing then archiving each."""
        print(f"[DELETE_ALL] Called with x-user-id={self._headers.get('x-user-id')}", flush=True)
        try:
            snapshot = await self.get_snapshot()
            agents = snapshot.get("agents", [])
            if not agents:
                return {"deleted_count": 0, "message": "No agents found to delete"}
            deleted = []
            errors = []
            async with httpx.AsyncClient(timeout=30.0) as client:
                for a in agents:
                    aid = a.get("id", "")
                    if not aid:
                        continue
                    resp = await client.delete(
                        f"{AGENT_ENGINE_URL}/agents/{aid}",
                        headers=self._headers,
                    )
                    if resp.status_code in (200, 204):
                        deleted.append({"id": aid, "name": a.get("name", "unknown")})
                    else:
                        errors.append({"id": aid, "name": a.get("name", "unknown"), "status": resp.status_code})
            result = {
                "deleted_count": len(deleted),
                "total": len(agents),
                "deleted": deleted,
            }
            if errors:
                result["errors"] = errors
                result["error_count"] = len(errors)
            return result
        except Exception as e:
            logger.error(f"[WorkspaceDB] delete_all_agents error: {e}")
            return {"error": str(e)}

    async def stop_run(self, run_id: str) -> Dict:
        """Cancel a running session via Agent Engine."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{AGENT_ENGINE_URL}/agents/sessions/{run_id}/cancel",
                    headers=self._headers,
                )
                if resp.status_code == 200:
                    return {"stopped": run_id}
                return {"error": f"Stop failed: {resp.status_code}"}
        except Exception as e:
            logger.error(f"[WorkspaceDB] stop_run error: {e}")
            return {"error": str(e)}

    async def set_trigger(self, agent_id: str, interval: str = "daily",
                          timezone: str = "UTC", **kw) -> Dict:
        """Create a trigger/schedule via Agent Engine API."""
        # Map simple intervals to cron expressions
        cron_map = {
            "minutely": "* * * * *",
            "hourly": "0 * * * *",
            "daily": "0 9 * * *",
            "weekly": "0 9 * * 1",
        }
        payload = {
            "trigger_type": "cron",
            "cron_expression": cron_map.get(interval, "0 9 * * *"),
            "timezone": timezone,
            "enabled": True,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{AGENT_ENGINE_URL}/agents/{agent_id}/triggers",
                    headers=self._headers, json=payload,
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return {"trigger_id": data.get("id", ""), "agent_id": agent_id, "interval": interval}
                return {"error": f"Trigger creation failed: {resp.status_code}"}
        except Exception as e:
            logger.error(f"[WorkspaceDB] set_trigger error: {e}")
            return {"error": str(e)}

    async def save_run(self, run_id: str, agent_id: str, outcome: str = "SUCCESS",
                       summary: str = "", loop_count: int = 0,
                       started_at=None, finished_at=None) -> Dict:
        """Store a build/run record via Agent Engine sessions API."""
        payload = {
            "agent_id": agent_id,
            "goal": summary or "Build agent",
            "status": "completed" if outcome == "SUCCESS" else "failed",
            "summary": summary,
            "loop_count": loop_count,
        }
        if started_at:
            payload["started_at"] = str(started_at)
        if finished_at:
            payload["finished_at"] = str(finished_at)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{AGENT_ENGINE_URL}/agents/{agent_id}/sessions",
                    headers=self._headers, json=payload,
                )
                if resp.status_code in (200, 201):
                    return {"run_id": run_id, "saved": True}
                logger.warning(f"[WorkspaceDB] save_run failed: {resp.status_code} {resp.text[:200]}")
                return {"run_id": run_id, "saved": False, "error": resp.text[:200]}
        except Exception as e:
            logger.warning(f"[WorkspaceDB] save_run error: {e}")
            return {"run_id": run_id, "saved": False, "error": str(e)}

    async def set_workspace_name(self, name: str, icon: str) -> Dict:
        """Workspace naming — stored in memory service as user preference."""
        return {"name": name, "icon": icon}

    async def list_databases(self) -> list:
        """List agents as databases (each agent has its own state)."""
        snapshot = await self.get_snapshot()
        return [
            {"agent_id": a.get("id", ""), "agent_name": a.get("name", "")}
            for a in snapshot.get("agents", [])
        ]
