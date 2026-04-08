"""Workspace DB — PostgreSQL (external DigitalOcean DB, persistent across restarts)"""
import json
import logging
from typing import Any, Dict, List, Optional

import asyncpg

from src.core.config import DATABASE_URL

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None

def _pg_url() -> str:
    url = DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    for suffix in ("?ssl=require", "&ssl=require", "?sslmode=require", "&sslmode=require"):
        url = url.replace(suffix, "")
    url = url.rstrip("?&")
    return url


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        import ssl as _ssl
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        _pool = await asyncpg.create_pool(_pg_url(), min_size=2, max_size=10, ssl=ctx)
        await _init_schema(_pool)
    return _pool


async def _init_schema(pool: asyncpg.Pool):
    async with pool.acquire() as c:
        await c.execute("""
            CREATE TABLE IF NOT EXISTS architect_workspaces(
                id TEXT PRIMARY KEY, name TEXT DEFAULT 'My Workspace', icon TEXT DEFAULT '🏢');
            CREATE TABLE IF NOT EXISTS architect_agents(
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT, goal TEXT,
                icon TEXT DEFAULT '🤖', system_prompt TEXT DEFAULT '',
                tools JSONB DEFAULT '[]', needs_build BOOLEAN DEFAULT TRUE,
                max_loops INT DEFAULT 30, temperature REAL DEFAULT 0.5,
                model TEXT DEFAULT 'groq/llama-3.3-70b-versatile',
                created_at TIMESTAMPTZ DEFAULT NOW());
            CREATE TABLE IF NOT EXISTS architect_runs(
                id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, outcome TEXT,
                summary TEXT DEFAULT '', loop_count INT DEFAULT 0,
                tool_calls JSONB DEFAULT '[]', tokens_used INT DEFAULT 0,
                errors JSONB DEFAULT '[]',
                started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ);
            CREATE TABLE IF NOT EXISTS architect_triggers(
                id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, trigger_type TEXT DEFAULT 'time',
                interval TEXT DEFAULT 'daily', timezone TEXT DEFAULT 'UTC',
                enabled BOOLEAN DEFAULT TRUE, created_at TIMESTAMPTZ DEFAULT NOW());
            CREATE INDEX IF NOT EXISTS idx_agents_ws ON architect_agents(workspace_id);
            CREATE INDEX IF NOT EXISTS idx_runs_agent ON architect_runs(agent_id);
        """)
    logger.info("[DB] Schema initialized")


class WorkspaceDB:
    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id

    async def get_snapshot(self) -> Dict:
        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT id, name, goal, icon, needs_build, model, created_at FROM architect_agents WHERE workspace_id=$1", self.workspace_id)
        agents = [dict(r) for r in rows]
        for a in agents:
            if a.get("created_at"):
                a["created_at"] = a["created_at"].isoformat()
        return {"agents": agents, "agent_count": len(agents)}

    async def save_agent(self, agent_id: str, name: str, goal: str, icon: str = "🤖",
                         system_prompt: str = "", tools: list = None, needs_build: bool = True,
                         max_loops: int = 30, temperature: float = 0.5,
                         model: str = "groq/llama-3.3-70b-versatile") -> Dict:
        pool = await get_pool()
        await pool.execute("""
            INSERT INTO architect_agents(id, workspace_id, name, goal, icon, system_prompt, tools, needs_build, max_loops, temperature, model)
            VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11)
            ON CONFLICT(id) DO UPDATE SET name=$3, goal=$4, icon=$5, system_prompt=$6,
                tools=$7::jsonb, needs_build=$8, max_loops=$9, temperature=$10, model=$11
        """, agent_id, self.workspace_id, name, goal, icon, system_prompt,
            json.dumps(tools or []), needs_build, max_loops, temperature, model)
        return {"agent_id": agent_id, "saved": True}

    async def get_agent(self, agent_id: str) -> Optional[Dict]:
        pool = await get_pool()
        r = await pool.fetchrow("SELECT * FROM architect_agents WHERE id=$1", agent_id)
        if not r:
            return None
        d = dict(r)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        return d

    async def get_agent_snapshot(self, agent_id: str) -> Dict:
        agent = await self.get_agent(agent_id)
        if not agent:
            return {"error": "Not found"}
        pool = await get_pool()
        runs = await pool.fetch(
            "SELECT * FROM architect_runs WHERE agent_id=$1 ORDER BY started_at DESC LIMIT 10", agent_id)
        run_list = []
        for r in runs:
            d = dict(r)
            for k in ("started_at", "finished_at"):
                if d.get(k):
                    d[k] = d[k].isoformat()
            run_list.append(d)
        return {"agent": agent, "recent_runs": run_list}

    async def get_run_snapshot(self, run_id: str) -> Dict:
        pool = await get_pool()
        r = await pool.fetchrow("SELECT * FROM architect_runs WHERE id=$1", run_id)
        if not r:
            return {"error": "Not found"}
        d = dict(r)
        for k in ("started_at", "finished_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        return d

    async def save_run(self, run_id: str, agent_id: str, outcome: str = None,
                       summary: str = "", loop_count: int = 0, tool_calls: list = None,
                       tokens_used: int = 0, errors: list = None,
                       started_at=None, finished_at=None) -> Dict:
        pool = await get_pool()
        await pool.execute("""
            INSERT INTO architect_runs(id, agent_id, outcome, summary, loop_count, tool_calls, tokens_used, errors, started_at, finished_at)
            VALUES($1,$2,$3,$4,$5,$6::jsonb,$7,$8::jsonb,$9,$10)
            ON CONFLICT(id) DO UPDATE SET outcome=$3, summary=$4, loop_count=$5,
                tool_calls=$6::jsonb, tokens_used=$7, errors=$8::jsonb, finished_at=$10
        """, run_id, agent_id, outcome, summary, loop_count,
            json.dumps(tool_calls or []), tokens_used, json.dumps(errors or []),
            started_at, finished_at)
        return {"run_id": run_id, "saved": True}

    async def delete_agent(self, agent_id: str) -> Dict:
        pool = await get_pool()
        await pool.execute("DELETE FROM architect_runs WHERE agent_id=$1", agent_id)
        await pool.execute("DELETE FROM architect_triggers WHERE agent_id=$1", agent_id)
        await pool.execute("DELETE FROM architect_agents WHERE id=$1", agent_id)
        return {"deleted": agent_id}

    async def stop_run(self, run_id: str) -> Dict:
        pool = await get_pool()
        await pool.execute("UPDATE architect_runs SET outcome='Stopped', finished_at=NOW() WHERE id=$1", run_id)
        return {"stopped": run_id}

    async def set_trigger(self, agent_id: str, interval: str = "daily",
                          timezone: str = "UTC", **kw) -> Dict:
        import uuid
        pool = await get_pool()
        tid = str(uuid.uuid4())
        await pool.execute("""
            INSERT INTO architect_triggers(id, agent_id, interval, timezone) VALUES($1,$2,$3,$4)
        """, tid, agent_id, interval, timezone)
        return {"trigger_id": tid, "agent_id": agent_id, "interval": interval}

    async def set_workspace_name(self, name: str, icon: str) -> Dict:
        pool = await get_pool()
        await pool.execute("""
            INSERT INTO architect_workspaces(id, name, icon) VALUES($1,$2,$3)
            ON CONFLICT(id) DO UPDATE SET name=$2, icon=$3
        """, self.workspace_id, name, icon)
        return {"name": name, "icon": icon}

    async def list_databases(self) -> list:
        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT id, name FROM architect_agents WHERE workspace_id=$1", self.workspace_id)
        return [{"agent_id": r["id"], "agent_name": r["name"]} for r in rows]
