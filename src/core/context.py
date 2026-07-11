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

# Provider keys in the BYOK/integrations response that are LLM providers, not
# third-party integrations — excluded when deriving "connected" integrations.
_LLM_PROVIDER_KEYS = {
    "anthropic", "openai", "google", "bedrock", "groq", "mistral",
    "openrouter", "cohere", "azure", "azure-openai",
}


async def fetch_workspace_context(workspace_id: str, user_id: str = "") -> Dict[str, Any]:
    uid = user_id or workspace_id
    ws_db = WorkspaceDB(workspace_id)
    memory = MemoryStore(workspace_id)
    registry = ToolRegistry()

    # NOTE: integration_client.get_integrations() calls auth_service's
    # /auth/integrations, which requires a full user Bearer JWT (401 for a
    # service-to-service x-user-id-only caller like this one) — it always
    # failed here, so "connected" was always empty. get_user_api_keys() hits
    # auth_service's internal endpoint (x-internal-service-key auth) instead,
    # which is the same one that actually works for BYOK/OAuth token lookups
    # elsewhere in the platform.
    snapshot, tools, user_memory, user_keys, economy = await asyncio.gather(
        ws_db.get_snapshot(),
        registry.list_all_tools(),
        memory.get_user_memory(),
        integration_client.get_user_api_keys(uid),
        billing_client.get_economic_state(uid),
        return_exceptions=True,
    )

    if isinstance(snapshot, Exception):
        logger.warning(f"[Context] snapshot failed: {snapshot}"); snapshot = {}
    if isinstance(tools, Exception):
        logger.warning(f"[Context] tools failed: {tools}"); tools = []
    if isinstance(user_memory, Exception):
        user_memory = {}
    if isinstance(user_keys, Exception):
        user_keys = {"keys": []}
    if isinstance(economy, Exception):
        economy = {"plan": "free", "credits_remaining": 0}

    connected = sorted(
        (k.get("provider") or "") for k in user_keys.get("keys", [])
        if k.get("provider") and k.get("provider") not in _LLM_PROVIDER_KEYS
    )

    return {
        "workspace": snapshot,
        "tools": tools,
        "user_memory": user_memory,
        "integrations": {
            "connected": connected,
            "raw": user_keys,
        },
        "economy": economy,
    }
