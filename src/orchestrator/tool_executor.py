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

    # ── Architect Self-Learning ──
    async def _tool_store_insight(self, a):
        return await self.memory.store_architect_insight(
            a.get("insight", ""), a.get("category", "observation"))
    async def _tool_retrieve_architect_context(self, a):
        return await self.memory.retrieve_architect_context()

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
