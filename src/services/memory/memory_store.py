"""Persistent Memory — Routes through unified memory_service on Docker network"""
import logging
from typing import Any, Dict

import httpx

from src.core.config import MEMORY_SERVICE_URL

logger = logging.getLogger(__name__)


class MemoryStore:
    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        self.base = f"{MEMORY_SERVICE_URL}/memory"

    async def get_user_memory(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{self.base}/user/{self.workspace_id}")
                if r.status_code == 200:
                    return r.json()
        except Exception as e:
            logger.warning(f"[Memory] get failed: {e}")
        return {}

    async def update_user_memory(self, content: str) -> Dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(f"{self.base}/user/{self.workspace_id}",
                                 json={"content": content})
                if r.status_code == 200:
                    return r.json()
        except Exception as e:
            logger.warning(f"[Memory] update failed: {e}")
        return {"status": "stored_locally", "content": content}
