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
        tools_needed = a.get("tools", [])
        missing = integration_client.check_required_integrations(tools_needed, connected_list)
        return {"connected": connected_list, "missing": missing}
    async def _tool_get_agent_settings(self, a):
        return await integration_client.get_agent_settings(self.user_id, a.get("agent_id", ""))

    # ── Blockchain / Identity ──
    async def _tool_get_agent_chain_status(self, a):
        return await chain_client.get_agent_chain_status(a.get("agent_id", ""))

    # ── Other ──
    async def _tool_open_interface_editor(self, a): return {"status": "editor_opened", "agent_id": a["agent_id"]}
    async def _tool_present_options(self, a):
        return {"type": a.get("question_type","PickOne"), "question": a.get("question",""), "options": a.get("options",[])}
    async def _tool_file(self, a):
        from src.services.file_ops.file_manager import FileManager
        return await FileManager(self.workspace_id).execute(a.get("action","list"), a)
    async def _tool_get_current_time(self, a): return datetime.now(timezone.utc).isoformat()
    async def _tool_configure_smtp(self, a): return {"status": "smtp_configured"}
