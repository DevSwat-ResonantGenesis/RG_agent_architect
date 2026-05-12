"""Integration Client — OAuth status, connect buttons via auth_service"""
import logging
import os
from typing import Dict, List

import httpx

logger = logging.getLogger(__name__)

AUTH_URL = "http://auth_service:8000"
_INTERNAL_KEY = os.getenv("AUTH_INTERNAL_SERVICE_KEY", "rg-internal-service-key-2025")


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
                data = r.json()
                # Ensure each integration has a consistent 'provider' field
                # Auth service returns 'id' (hyphenated) and 'provider' (group)
                # We need both for matching
                for item in data.get("integrations", []):
                    if "id" in item and "provider" not in item:
                        item["provider"] = item["id"]
                return data
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
    # Maps tool names to auth service integration IDs (hyphenated)
    TOOL_TO_INTEGRATION = {
        "google_sheets": "google-drive",
        "documents": "google-drive",
        "gmail": "gmail",
        "google_calendar": "google-calendar",
        "google_drive": "google-drive",
        "slack": "slack",
        "github": "github",
        "notion": "notion",
        "discord": "discord",
        "linkedin": "linkedin",
        "hubspot": "hubspot",
        "salesforce": "salesforce",
    }
    # Normalize connected list: handle both "google-drive" and "google_drive" and "google"
    connected_normalized = set()
    for c in connected:
        connected_normalized.add(c)
        connected_normalized.add(c.replace("-", "_"))
        connected_normalized.add(c.replace("_", "-"))

    missing = []
    for tool in agent_tools:
        integration = TOOL_TO_INTEGRATION.get(tool)
        if integration and integration not in connected_normalized:
            # Also check if the provider group (e.g. "google") is connected
            provider = integration.split("-")[0]
            if provider not in connected_normalized:
                missing.append({
                    "integration": integration,
                    "required_by": tool,
                    "action": "connect",
                    "connect_url": f"/settings/integrations",
                    "message": f"Connect {integration.replace('-', ' ').title()} to use {tool}",
                })
    return missing


async def get_user_api_keys(user_id: str) -> Dict:
    """Get user's API keys for external services."""
    try:
        headers = {"x-internal-service-key": _INTERNAL_KEY}
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{AUTH_URL}/auth/internal/user-api-keys/{user_id}", headers=headers)
            if r.status_code == 200:
                return r.json()
            logger.warning(f"[Auth] get user api keys returned {r.status_code}")
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
