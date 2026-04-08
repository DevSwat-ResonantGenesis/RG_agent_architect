"""Integration Client — OAuth status, connect buttons via auth_service"""
import logging
from typing import Dict, List

import httpx

logger = logging.getLogger(__name__)

AUTH_URL = "http://auth_service:8000"


async def get_integrations(user_id: str, token: str = "") -> Dict:
    """Get all connected integrations for a user."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if user_id:
        headers["x-user-id"] = user_id
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{AUTH_URL}/auth/integrations", headers=headers)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f"[Auth] get integrations failed: {e}")
    return {"integrations": []}


async def get_integration_status(user_id: str, integration_id: str, token: str = "") -> Dict:
    """Check if specific integration is connected."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if user_id:
        headers["x-user-id"] = user_id
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{AUTH_URL}/auth/integrations/{integration_id}/status", headers=headers)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f"[Auth] integration status failed: {e}")
    return {"connected": False}


def check_required_integrations(agent_tools: List[str], connected: List[str]) -> List[Dict]:
    """Return list of missing integrations with connect actions for frontend."""
    TOOL_TO_INTEGRATION = {
        "google_sheets": "google_drive",
        "documents": "google_docs",
        "gmail": "gmail",
        "google_calendar": "google_calendar",
        "google_drive": "google_drive",
        "slack": "slack",
        "github": "github",
        "notion": "notion",
        "discord": "discord",
        "linkedin": "linkedin",
        "hubspot": "hubspot",
        "salesforce": "salesforce",
    }
    missing = []
    connected_set = set(connected)
    for tool in agent_tools:
        integration = TOOL_TO_INTEGRATION.get(tool)
        if integration and integration not in connected_set:
            missing.append({
                "integration": integration,
                "required_by": tool,
                "action": "connect",
                "connect_url": f"/oauth/{integration}/login",
                "message": f"Connect {integration} to use {tool}",
            })
    return missing


async def get_user_api_keys(user_id: str) -> Dict:
    """Get user's API keys for external services."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{AUTH_URL}/auth/internal/user-api-keys/{user_id}")
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f"[Auth] get user api keys failed: {e}")
    return {"keys": []}


async def get_agent_settings(user_id: str, agent_id: str, token: str = "") -> Dict:
    """Get agent-specific settings from auth service."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if user_id:
        headers["x-user-id"] = user_id
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{AUTH_URL}/auth/settings/agents/{agent_id}", headers=headers)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f"[Auth] get agent settings failed: {e}")
    return {}
