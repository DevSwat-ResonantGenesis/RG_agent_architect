"""Workspace DB — Per-agent SQLite, cross-agent READ-ONLY"""
import json, os, sqlite3
from typing import Any, Dict, List, Optional
from src.core.config import WORKSPACE_DB_DIR
from src.models.agent import Agent, Run


class WorkspaceDB:
    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        self.db_path = os.path.join(WORKSPACE_DB_DIR, f"{workspace_id}.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        c = sqlite3.connect(self.db_path)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY, name TEXT, goal TEXT, icon TEXT DEFAULT '🤖',
                system_prompt TEXT DEFAULT '', tools TEXT DEFAULT '[]', db_path TEXT DEFAULT '',
                interface_url TEXT, needs_build INT DEFAULT 1, max_loops INT DEFAULT 30,
                temperature REAL DEFAULT 0.5, model TEXT DEFAULT 'groq/llama-3.3-70b', created_at TEXT);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, agent_id TEXT, outcome TEXT,
                summary TEXT DEFAULT '', loop_count INT DEFAULT 0, tool_calls TEXT DEFAULT '[]',
                tokens_used INT DEFAULT 0, errors TEXT DEFAULT '[]', started_at TEXT, finished_at TEXT);
            CREATE TABLE IF NOT EXISTS workspace(id TEXT PRIMARY KEY, name TEXT DEFAULT 'My Workspace', icon TEXT DEFAULT '🏢');
        """)
        c.close()

    async def get_snapshot(self) -> Dict:
        c = sqlite3.connect(self.db_path); c.row_factory = sqlite3.Row
        agents = [dict(r) for r in c.execute("SELECT * FROM agents").fetchall()]
        c.close()
        return {"agents": agents, "agent_count": len(agents)}

    async def save_agent(self, a: Agent):
        c = sqlite3.connect(self.db_path)
        c.execute("INSERT OR REPLACE INTO agents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (a.id, a.name, a.goal, a.icon, a.system_prompt, json.dumps(a.tools),
             a.db_path, a.interface_url, int(a.needs_build), a.max_loops, a.temperature,
             a.model, a.created_at.isoformat()))
        c.commit(); c.close()

    async def get_agent(self, agent_id: str) -> Optional[Agent]:
        c = sqlite3.connect(self.db_path); c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone(); c.close()
        if not r: return None
        return Agent(id=r["id"], name=r["name"], goal=r["goal"], icon=r["icon"],
                     system_prompt=r["system_prompt"], tools=json.loads(r["tools"]),
                     needs_build=bool(r["needs_build"]), max_loops=r["max_loops"],
                     temperature=r["temperature"], model=r["model"])

    async def get_agent_snapshot(self, agent_id: str) -> Dict:
        agent = await self.get_agent(agent_id)
        if not agent: return {"error": "Not found"}
        c = sqlite3.connect(self.db_path); c.row_factory = sqlite3.Row
        runs = [dict(r) for r in c.execute("SELECT * FROM runs WHERE agent_id=? ORDER BY started_at DESC LIMIT 10", (agent_id,)).fetchall()]
        c.close()
        return {"agent": agent.__dict__, "recent_runs": runs}

    async def get_run_snapshot(self, run_id: str) -> Dict:
        c = sqlite3.connect(self.db_path); c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone(); c.close()
        return dict(r) if r else {"error": "Not found"}

    async def save_run(self, agent_id: str, run: Run):
        c = sqlite3.connect(self.db_path)
        c.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?,?,?,?,?,?)",
            (run.id, agent_id, run.outcome.value if run.outcome else None, run.summary,
             run.loop_count, json.dumps(run.tool_calls), run.tokens_used, json.dumps(run.errors),
             run.started_at.isoformat() if run.started_at else None,
             run.finished_at.isoformat() if run.finished_at else None))
        c.commit(); c.close()

    async def delete_agent(self, aid: str) -> Dict:
        c = sqlite3.connect(self.db_path)
        c.execute("DELETE FROM agents WHERE id=?", (aid,))
        c.execute("DELETE FROM runs WHERE agent_id=?", (aid,))
        c.commit(); c.close()
        return {"deleted": aid}

    async def stop_run(self, rid: str) -> Dict:
        c = sqlite3.connect(self.db_path)
        c.execute("UPDATE runs SET outcome='Stopped' WHERE id=?", (rid,))
        c.commit(); c.close()
        return {"stopped": rid}

    async def set_trigger(self, agent_id: str, **kw) -> Dict:
        return {"agent_id": agent_id, "trigger": kw}

    async def set_workspace_name(self, name: str, icon: str) -> Dict:
        c = sqlite3.connect(self.db_path)
        c.execute("INSERT OR REPLACE INTO workspace VALUES(?,?,?)", (self.workspace_id, name, icon))
        c.commit(); c.close()
        return {"name": name, "icon": icon}

    async def list_databases(self) -> list:
        c = sqlite3.connect(self.db_path); c.row_factory = sqlite3.Row
        rows = c.execute("SELECT id, name FROM agents").fetchall(); c.close()
        return [{"agent_id": r["id"], "agent_name": r["name"]} for r in rows]
