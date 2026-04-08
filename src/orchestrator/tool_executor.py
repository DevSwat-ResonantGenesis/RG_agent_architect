"""Tool Executor — Implements all 21 orchestrator tools"""
from datetime import datetime, timezone
from typing import Any, Dict

from src.services.database.workspace_db import WorkspaceDB
from src.services.memory.memory_store import MemoryStore


class ToolExecutor:
    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        self.ws_db = WorkspaceDB(workspace_id)
        self.memory = MemoryStore(workspace_id)

    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        handler = getattr(self, f"_tool_{tool_name}", None)
        if not handler:
            raise ValueError(f"Unknown tool: {tool_name}")
        return await handler(arguments)

    async def _tool_workspace_snapshot(self, a): return await self.ws_db.get_snapshot()
    async def _tool_list_workspace_tools(self, a):
        from src.tools.builtin.registry import ToolRegistry
        return await ToolRegistry().list_all_tools()
    async def _tool_get_user_memory(self, a): return await self.memory.get_user_memory()
    async def _tool_update_user_memory(self, a): return await self.memory.update_user_memory(a.get("content",""))
    async def _tool_agent_snapshot(self, a): return await self.ws_db.get_agent_snapshot(a["agent_id"])
    async def _tool_run_snapshot(self, a): return await self.ws_db.get_run_snapshot(a["run_id"])
    async def _tool_build_agent(self, a):
        from src.builder.builder import Builder
        return await Builder(self.workspace_id).build(a.get("name",""), a.get("goal",""), a.get("icon","🤖"))
    async def _tool_continue_build(self, a):
        from src.builder.builder import Builder
        return await Builder(self.workspace_id).continue_build(a["agent_id"], a.get("instructions",""))
    async def _tool_message_build(self, a):
        from src.builder.builder import Builder
        return await Builder(self.workspace_id).message_build(a["agent_id"], a.get("message",""))
    async def _tool_run_agent(self, a):
        from src.runner.runner import Runner
        return await Runner(self.workspace_id).run(a["agent_id"], a.get("goal"))
    async def _tool_stop_run(self, a): return await self.ws_db.stop_run(a["run_id"])
    async def _tool_delete_agent(self, a): return await self.ws_db.delete_agent(a["agent_id"])
    async def _tool_set_trigger(self, a): return await self.ws_db.set_trigger(a["agent_id"], **a)
    async def _tool_set_workspace_name(self, a): return await self.ws_db.set_workspace_name(a.get("name",""), a.get("icon",""))
    async def _tool_open_interface_editor(self, a): return {"status": "editor_opened", "agent_id": a["agent_id"]}
    async def _tool_present_options(self, a):
        return {"type": a.get("question_type","PickOne"), "question": a.get("question",""), "options": a.get("options",[])}
    async def _tool_file(self, a):
        from src.services.file_ops.file_manager import FileManager
        return await FileManager(self.workspace_id).execute(a.get("action","list"), a)
    async def _tool_get_current_time(self, a): return datetime.now(timezone.utc).isoformat()
    async def _tool_configure_smtp(self, a): return {"status": "smtp_configured"}
    async def _tool_list_workspace_databases(self, a): return await self.ws_db.list_databases()
    async def _tool_get_credits_info(self, a): return {"plan": "free", "credits_remaining": 2200}
