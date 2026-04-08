"""Session init: parallel calls for workspace, tools, memory, integrations, billing"""
import asyncio
import logging
from typing import Any, Dict

from src.services.database.workspace_db import WorkspaceDB
from src.services.memory.memory_store import MemoryStore
from src.services.billing import billing_client
from src.services.auth import integration_client
from src.tools.builtin.registry import ToolRegistry

logger = logging.getLogger(__name__)


async def fetch_workspace_context(workspace_id: str, user_id: str = "") -> Dict[str, Any]:
    uid = user_id or workspace_id
    ws_db = WorkspaceDB(workspace_id)
    memory = MemoryStore(workspace_id)
    registry = ToolRegistry()

    snapshot, tools, user_memory, integrations, economy = await asyncio.gather(
        ws_db.get_snapshot(),
        registry.list_all_tools(),
        memory.get_user_memory(),
        integration_client.get_integrations(uid),
        billing_client.get_economic_state(uid),
        return_exceptions=True,
    )

    if isinstance(snapshot, Exception):
        logger.warning(f"[Context] snapshot failed: {snapshot}"); snapshot = {}
    if isinstance(tools, Exception):
        logger.warning(f"[Context] tools failed: {tools}"); tools = []
    if isinstance(user_memory, Exception):
        user_memory = {}
    if isinstance(integrations, Exception):
        integrations = {"integrations": []}
    if isinstance(economy, Exception):
        economy = {"plan": "free", "credits_remaining": 0}

    connected = [i.get("provider", "") for i in integrations.get("integrations", [])]

    return {
        "workspace": snapshot,
        "tools": tools,
        "user_memory": user_memory,
        "integrations": {
            "connected": connected,
            "raw": integrations,
        },
        "economy": economy,
    }
