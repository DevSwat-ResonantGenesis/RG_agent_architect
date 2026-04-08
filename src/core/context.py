"""Session init: 3 parallel calls (workspace_snapshot + list_tools + get_memory)"""
import asyncio
from typing import Any, Dict

from src.services.database.workspace_db import WorkspaceDB
from src.services.memory.memory_store import MemoryStore
from src.tools.builtin.registry import ToolRegistry


async def fetch_workspace_context(workspace_id: str) -> Dict[str, Any]:
    ws_db = WorkspaceDB(workspace_id)
    memory = MemoryStore(workspace_id)
    registry = ToolRegistry()
    snapshot, tools, user_memory = await asyncio.gather(
        ws_db.get_snapshot(),
        registry.list_all_tools(),
        memory.get_user_memory(),
    )
    return {"workspace": snapshot, "tools": tools, "user_memory": user_memory}
