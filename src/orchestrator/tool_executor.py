"""Tool Executor — Full integration: blockchain, billing, memory, auth, tools"""
from datetime import datetime, timezone
from typing import Any, Dict

from src.services.database.workspace_db import WorkspaceDB
from src.services.memory.memory_store import MemoryStore
from src.services.billing import billing_client
from src.services.blockchain import chain_client
from src.services.auth import integration_client


class ToolExecutor:
    def __init__(self, workspace_id: str, user_id: str = ""):
        self.workspace_id = workspace_id
        self.user_id = user_id or workspace_id
        self.ws_db = WorkspaceDB(workspace_id)
        self.memory = MemoryStore(workspace_id)

    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        handler = getattr(self, f"_tool_{tool_name}", None)
        if not handler:
            raise ValueError(f"Unknown tool: {tool_name}")
        return await handler(arguments)

    # ── Workspace ──
    async def _tool_workspace_snapshot(self, a): return await self.ws_db.get_snapshot()
    async def _tool_list_workspace_tools(self, a):
        from src.tools.builtin.registry import ToolRegistry
        return await ToolRegistry().list_all_tools()
    async def _tool_set_workspace_name(self, a): return await self.ws_db.set_workspace_name(a.get("name",""), a.get("icon",""))
    async def _tool_list_workspace_databases(self, a): return await self.ws_db.list_databases()

    # ── Memory (dual hash sphere: user + agent) ──
    async def _tool_get_user_memory(self, a): return await self.memory.get_user_memory()
    async def _tool_update_user_memory(self, a): return await self.memory.update_user_memory(a.get("content",""))
    async def _tool_get_agent_memory(self, a):
        m = MemoryStore(self.workspace_id, a.get("agent_id", ""))
        return await m.get_agent_memory()
    async def _tool_get_dual_memory(self, a):
        m = MemoryStore(self.workspace_id, a.get("agent_id", ""))
        return await m.get_dual_memory()
    async def _tool_ask_memory(self, a):
        m = MemoryStore(self.workspace_id, a.get("agent_id", ""))
        return await m.ask_memory(a.get("question", ""))

    # ── Agent snapshots ──
    async def _tool_agent_snapshot(self, a):
        snap = await self.ws_db.get_agent_snapshot(a["agent_id"])
        chain = await chain_client.get_agent_chain_status(a["agent_id"])
        if chain:
            snap["blockchain"] = chain
        return snap
    async def _tool_run_snapshot(self, a): return await self.ws_db.get_run_snapshot(a["run_id"])

    # ── Build / Run ──
    async def _tool_build_agent(self, a):
        from src.builder.builder import Builder
        return await Builder(self.workspace_id, self.user_id).build(
            name=a.get("name",""), goal=a.get("goal",""), icon=a.get("icon","🤖"),
            tools=a.get("tools", []), max_loops=a.get("max_loops", 30),
            temperature=a.get("temperature", 0.5), model=a.get("model", "groq/llama-3.3-70b-versatile"))
    async def _tool_continue_build(self, a):
        from src.builder.builder import Builder
        return await Builder(self.workspace_id, self.user_id).continue_build(a["agent_id"], a.get("instructions",""))
    async def _tool_message_build(self, a):
        from src.builder.builder import Builder
        return await Builder(self.workspace_id, self.user_id).message_build(a["agent_id"], a.get("message",""))
    async def _tool_run_agent(self, a):
        from src.runner.runner import Runner
        return await Runner(self.workspace_id).run(a["agent_id"], a.get("goal"), user_id=self.user_id)
    async def _tool_stop_run(self, a): return await self.ws_db.stop_run(a["run_id"])
    async def _tool_delete_agent(self, a): return await self.ws_db.delete_agent(a["agent_id"])
    async def _tool_delete_all_agents(self, a): return await self.ws_db.delete_all_agents()
    async def _tool_modify_agent(self, a):
        from src.builder.builder import Builder
        add_tools = [t.strip() for t in a.get("add_tools", "").split(",") if t.strip()] if a.get("add_tools") else None
        remove_tools = [t.strip() for t in a.get("remove_tools", "").split(",") if t.strip()] if a.get("remove_tools") else None
        updates = {}
        if a.get("max_loops"): updates["max_loops"] = int(a["max_loops"])
        if a.get("temperature"): updates["temperature"] = float(a["temperature"])
        if a.get("model"): updates["model"] = a["model"]
        return await Builder(self.workspace_id, self.user_id).modify_agent(
            a["agent_id"], add_tools=add_tools, remove_tools=remove_tools, **updates)

    # ── Scheduling ──
    async def _tool_set_trigger(self, a):
        return await self.ws_db.set_trigger(a["agent_id"], interval=a.get("interval","daily"), timezone=a.get("timezone","UTC"))

    # ── Billing / Economy ──
    async def _tool_get_credits_info(self, a):
        return await billing_client.get_economic_state(self.user_id)
    async def _tool_check_credits(self, a):
        return await billing_client.check_credits(self.user_id)

    # ── Integrations / OAuth ──
    async def _tool_check_integrations(self, a):
        connected = await integration_client.get_integrations(self.user_id)
        connected_list = [i.get("provider", "") for i in connected.get("integrations", [])]
        tools_raw = a.get("tools", "")
        if isinstance(tools_raw, str):
            tools_needed = [t.strip() for t in tools_raw.split(",") if t.strip()]
        else:
            tools_needed = tools_raw or []
        missing = integration_client.check_required_integrations(tools_needed, connected_list)
        return {"connected": connected_list, "missing": missing}
    async def _tool_get_agent_settings(self, a):
        return await integration_client.get_agent_settings(self.user_id, a.get("agent_id", ""))

    # ── Blockchain / Identity ──
    async def _tool_get_agent_chain_status(self, a):
        return await chain_client.get_agent_chain_status(a.get("agent_id", ""))

    # ── Prompt Management (read/write/modify system_prompt per agent) ──
    async def _tool_get_agent_prompt(self, a):
        """Read an agent's current system prompt via Agent Engine."""
        agent = await self.ws_db.get_agent(a["agent_id"])
        if not agent:
            return {"error": "Agent not found"}
        return {
            "agent_id": a["agent_id"],
            "name": agent.get("name", ""),
            "system_prompt": agent.get("system_prompt", ""),
            "model": agent.get("model", ""),
            "provider": agent.get("provider", ""),
        }

    async def _tool_update_agent_prompt(self, a):
        """Write or replace an agent's system prompt via Agent Engine PATCH."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        payload = {"system_prompt": a["prompt"]}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.patch(
                    f"{AGENT_ENGINE_URL}/agents/{a['agent_id']}",
                    headers=self.ws_db._headers, json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {"updated": True, "agent_id": a["agent_id"],
                            "updated_fields": data.get("updated_fields", ["system_prompt"])}
                return {"error": f"PATCH failed: {resp.status_code} {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Agent Config (model, temperature, mode, tools via Agent Engine PATCH) ──
    async def _tool_update_agent_config(self, a):
        """Update agent configuration fields: model, temperature, max_tokens, mode, tools."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        updatable = ("model", "temperature", "max_tokens", "mode", "tools",
                     "provider", "is_active", "max_loops", "tool_mode")
        payload = {k: a[k] for k in updatable if k in a}
        if not payload:
            return {"error": "No valid fields to update. Accepted: " + ", ".join(updatable)}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.patch(
                    f"{AGENT_ENGINE_URL}/agents/{a['agent_id']}",
                    headers=self.ws_db._headers, json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {"updated": True, "agent_id": a["agent_id"],
                            "updated_fields": data.get("updated_fields", list(payload.keys()))}
                return {"error": f"PATCH failed: {resp.status_code} {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Schedules (create cron via Agent Engine) ──
    async def _tool_create_schedule(self, a):
        """Create a cron schedule for an agent via Agent Engine."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        payload = {
            "cron_expression": a.get("cron", "0 9 * * *"),
            "goal": a.get("goal", ""),
            "timezone": a.get("timezone", "UTC"),
            "enabled": True,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{AGENT_ENGINE_URL}/agents/{a['agent_id']}/schedules",
                    headers=self.ws_db._headers, json=payload,
                )
                if resp.status_code in (200, 201):
                    return resp.json()
                return {"error": f"Schedule creation failed: {resp.status_code} {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Sessions / Steps (read execution history) ──
    async def _tool_get_agent_sessions(self, a):
        """Get recent sessions for an agent."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{AGENT_ENGINE_URL}/agents/{a['agent_id']}/sessions",
                    headers=self.ws_db._headers,
                )
                if resp.status_code == 200:
                    sessions = resp.json()
                    if isinstance(sessions, list):
                        return {"sessions": sessions[:10], "count": len(sessions)}
                    return sessions
                return {"error": f"Failed: {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_get_session_steps(self, a):
        """Get step-by-step execution trace for a session."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{AGENT_ENGINE_URL}/agents/sessions/{a['session_id']}/steps",
                    headers=self.ws_db._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"Failed: {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Agent Delegation (spawn / use any agent) ──
    async def _tool_delegate_to_agent(self, a):
        """Delegate a sub-task to any existing agent and return its result.

        This lets the architect use any agent as a worker:
        e.g. "ask my research agent to find info about X"
        """
        from src.runner.runner import Runner
        agent_id = a["agent_id"]
        task = a.get("task", a.get("goal", ""))
        if not task:
            return {"error": "No task/goal provided for delegation"}

        # Verify agent exists
        agent = await self.ws_db.get_agent(agent_id)
        if not agent:
            return {"error": f"Agent {agent_id} not found — cannot delegate"}

        agent_name = agent.get("name", "unknown")
        runner = Runner(self.workspace_id)
        result = await runner.run(agent_id, goal_override=task, user_id=self.user_id)
        return {
            "delegated_to": agent_name,
            "agent_id": agent_id,
            "task": task,
            "outcome": result.get("outcome", "UNKNOWN"),
            "summary": result.get("summary", ""),
            "run_id": result.get("run_id", ""),
            "loops": result.get("loops", 0),
        }

    async def _tool_delegate_by_name(self, a):
        """Delegate a sub-task to an agent by NAME (looks up ID automatically)."""
        name = a.get("agent_name", "").strip()
        task = a.get("task", a.get("goal", ""))
        if not name:
            return {"error": "No agent_name provided"}
        if not task:
            return {"error": "No task/goal provided for delegation"}

        snapshot = await self.ws_db.get_snapshot()
        agents = snapshot.get("agents", [])
        match = None
        name_lower = name.lower()
        for ag in agents:
            if ag.get("name", "").lower() == name_lower:
                match = ag
                break
        if not match:
            # Fuzzy: partial match
            for ag in agents:
                if name_lower in ag.get("name", "").lower():
                    match = ag
                    break
        if not match:
            available = [ag.get("name", "?") for ag in agents]
            return {"error": f"Agent '{name}' not found. Available: {available}"}

        return await self._tool_delegate_to_agent({
            "agent_id": match["id"], "task": task})

    # ── TODO / Planning / Brainstorm (persistent, per-agent + workspace) ──
    async def _tool_create_task(self, a):
        """Create a TODO task. Scope: per-agent (if agent_id given) or workspace-wide."""
        import uuid as _uuid
        task = {
            "id": a.get("id") or str(_uuid.uuid4())[:8],
            "title": a.get("title", ""),
            "description": a.get("description", ""),
            "status": a.get("status", "pending"),
            "priority": a.get("priority", "medium"),
            "agent_id": a.get("agent_id", ""),
            "tags": a.get("tags", ""),
        }
        scope_agent = a.get("agent_id", "")
        mem = MemoryStore(self.workspace_id, scope_agent)
        result = await mem.store_task(task)
        return {"created": True, "task": task, **result}

    async def _tool_list_tasks(self, a):
        """List TODO tasks. Filter by agent_id or get all workspace tasks."""
        agent_id = a.get("agent_id", "")
        query = a.get("query", "all tasks and plans")
        mem = MemoryStore(self.workspace_id)
        return await mem.search_tasks(query=query, agent_id=agent_id)

    async def _tool_update_task(self, a):
        """Update a task's status/content by creating a new version (append-only memory)."""
        import uuid as _uuid
        task = {
            "id": a.get("task_id", ""),
            "title": a.get("title", ""),
            "status": a.get("status", ""),
            "priority": a.get("priority", ""),
            "description": a.get("description", ""),
            "agent_id": a.get("agent_id", ""),
            "updated": True,
        }
        # Remove empty fields
        task = {k: v for k, v in task.items() if v}
        scope_agent = a.get("agent_id", "")
        mem = MemoryStore(self.workspace_id, scope_agent)
        result = await mem.store_task(task)
        return {"updated": True, "task": task, **result}

    async def _tool_brainstorm(self, a):
        """Store a brainstorm idea or plan. Scope: per-agent or workspace-wide."""
        content = a.get("content", a.get("idea", ""))
        agent_id = a.get("agent_id", "")
        if not content:
            return {"error": "No content/idea provided"}
        mem = MemoryStore(self.workspace_id)
        result = await mem.store_brainstorm(content, agent_id=agent_id)
        return {"stored": True, "content": content, "agent_id": agent_id, **result}

    async def _tool_get_workspace_plan(self, a):
        """Get full workspace plan: all tasks + brainstorms across all agents."""
        mem = MemoryStore(self.workspace_id)
        tasks = await mem.search_tasks(query="all tasks plans TODO", limit=50)
        brainstorms = await mem.search_brainstorms(query="brainstorm ideas plans", limit=20)
        # Also get per-agent tasks for each agent
        snapshot = await self.ws_db.get_snapshot()
        agents = snapshot.get("agents", [])
        per_agent = {}
        for ag in agents[:10]:  # cap at 10 agents
            aid = ag.get("id", "")
            aname = ag.get("name", "?")
            agent_tasks = await mem.search_tasks(query="tasks", agent_id=aid, limit=10)
            if agent_tasks:
                per_agent[aname] = agent_tasks
        return {
            "workspace_tasks": tasks,
            "brainstorms": brainstorms,
            "per_agent_tasks": per_agent,
            "agent_count": len(agents),
        }

    # ── Architect Self-Learning ──
    async def _tool_store_insight(self, a):
        return await self.memory.store_architect_insight(
            a.get("insight", ""), a.get("category", "observation"))
    async def _tool_retrieve_architect_context(self, a):
        return await self.memory.retrieve_architect_context()

    # ── Session Control (cancel, approve, emergency stop) ──
    async def _tool_cancel_session(self, a):
        """Cancel a running session via Agent Engine."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{AGENT_ENGINE_URL}/agents/sessions/{a['session_id']}/cancel",
                    headers=self.ws_db._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"Cancel failed: {resp.status_code} {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_emergency_stop(self, a):
        """Emergency stop — cancel ALL sessions and disable ALL schedules for an agent."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{AGENT_ENGINE_URL}/agents/{a['agent_id']}/emergency-stop",
                    headers=self.ws_db._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"Emergency stop failed: {resp.status_code} {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_approve_step(self, a):
        """Approve a pending step via Agent Engine."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{AGENT_ENGINE_URL}/agents/sessions/{a['session_id']}/approve/{a['step_id']}",
                    headers=self.ws_db._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"Approve failed: {resp.status_code} {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_get_pending_approvals(self, a):
        """Get all pending approval requests."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{AGENT_ENGINE_URL}/agents/approvals/pending",
                    headers=self.ws_db._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"Failed: {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Full Tool Registry + Direct Execution ──
    async def _tool_list_engine_tools(self, a):
        """List ALL 74+ platform tools from Agent Engine."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{AGENT_ENGINE_URL}/agents/tools/list",
                    headers=self.ws_db._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"Failed: {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_execute_tool(self, a):
        """Execute any platform tool directly for testing."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        payload = {
            "tool_name": a.get("tool_name", ""),
            "tool_input": a.get("tool_input", {}),
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{AGENT_ENGINE_URL}/agents/tools/execute",
                    headers=self.ws_db._headers, json=payload,
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"Execute failed: {resp.status_code} {resp.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Provider & Metrics ──
    async def _tool_list_providers(self, a):
        """List all available LLM providers and their status."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{AGENT_ENGINE_URL}/agents/providers",
                    headers=self.ws_db._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"Failed: {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_get_agent_metrics(self, a):
        """Get agent performance metrics."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{AGENT_ENGINE_URL}/agents/{a['agent_id']}/metrics",
                    headers=self.ws_db._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"Failed: {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Schedule Management ──
    async def _tool_list_schedules(self, a):
        """List all schedules for an agent."""
        import httpx
        from src.core.config import AGENT_ENGINE_URL
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{AGENT_ENGINE_URL}/agents/{a['agent_id']}/schedules",
                    headers=self.ws_db._headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"Failed: {resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Other ──
    async def _tool_open_interface_editor(self, a): return {"status": "editor_opened", "agent_id": a["agent_id"]}
    async def _tool_present_options(self, a):
        opts = a.get("options", "")
        if isinstance(opts, str):
            opts = [o.strip() for o in opts.split(",") if o.strip()]
        return {"type": "PickOne", "question": a.get("question", ""), "options": opts}
    async def _tool_file(self, a):
        from src.services.file_ops.file_manager import FileManager
        return await FileManager(self.workspace_id).execute(a.get("action","list"), a)
    async def _tool_get_current_time(self, a): return datetime.now(timezone.utc).isoformat()
    async def _tool_configure_smtp(self, a): return {"status": "smtp_configured"}
