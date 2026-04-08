"""Blockchain Client — Agent identity, wallet, on-chain registration via blockchain_service"""
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

BLOCKCHAIN_URL = "http://blockchain_service:8000"


async def _post(path: str, body: Dict) -> Dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{BLOCKCHAIN_URL}{path}", json=body)
            if r.status_code == 200:
                return r.json()
            logger.warning(f"[Blockchain] {path} → {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"[Blockchain] {path} failed: {e}")
    return {}


async def _get(path: str) -> Dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{BLOCKCHAIN_URL}{path}")
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f"[Blockchain] GET {path} failed: {e}")
    return {}


async def register_agent_identity(agent_id: str, name: str, workspace_id: str, owner_id: str = "") -> Dict:
    """Create agent identity hash on blockchain."""
    result = await _post("/blockchain/hash/agent-identity", {
        "agent_id": agent_id,
        "name": name,
        "workspace_id": workspace_id,
        "owner_id": owner_id,
    })
    logger.info(f"[Blockchain] Agent identity hash: {result.get('hash', 'N/A')}")
    return result


async def register_on_chain(agent_id: str, name: str, owner_id: str = "") -> Dict:
    """Register agent on internal blockchain."""
    result = await _post("/blockchain/register-on-chain", {
        "agent_id": agent_id,
        "name": name,
        "owner_id": owner_id,
        "type": "agent",
    })
    logger.info(f"[Blockchain] On-chain registration: {result.get('status', 'N/A')}")
    return result


async def create_agent_block(agent_id: str, name: str, goal: str, owner_id: str = "") -> Dict:
    """Create agent block in blockchain."""
    return await _post("/blockchain/blocks/agent", {
        "agent_id": agent_id,
        "name": name,
        "goal": goal,
        "owner_id": owner_id,
    })


async def create_agent_wallet(agent_id: str, owner_id: str = "") -> Dict:
    """Create wallet for agent."""
    result = await _post("/blockchain/wallet/create", {
        "entity_id": agent_id,
        "entity_type": "agent",
        "owner_id": owner_id,
    })
    logger.info(f"[Blockchain] Wallet created: {result.get('address', 'N/A')}")
    return result


async def create_agent_hash_sphere(agent_id: str, name: str) -> Dict:
    """Create hash sphere for agent memory."""
    return await _post("/blockchain/hash/agent-sphere", {
        "agent_id": agent_id,
        "name": name,
    })


async def create_user_hash_sphere(user_id: str) -> Dict:
    """Create/get user hash sphere."""
    return await _post("/blockchain/hash/user-sphere", {
        "user_id": user_id,
    })


async def get_agent_chain_status(agent_id: str) -> Dict:
    """Check agent's blockchain registration status."""
    return await _get(f"/blockchain/agent-chain-status/{agent_id}")


async def register_identity(user_hash: str, agent_id: str = "") -> Dict:
    """Register identity in identity service."""
    return await _post("/identity/register", {
        "user_hash": user_hash,
        "agent_id": agent_id,
    })
