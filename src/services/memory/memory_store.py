"""Persistent Memory — name, role, company, timezone, preferences"""
import json, os
from typing import Any, Dict
from src.core.config import MEMORY_DIR


class MemoryStore:
    def __init__(self, workspace_id: str):
        self.path = os.path.join(MEMORY_DIR, f"{workspace_id}.json")
        os.makedirs(MEMORY_DIR, exist_ok=True)

    async def get_user_memory(self) -> Dict[str, Any]:
        if not os.path.exists(self.path): return {}
        with open(self.path) as f: return json.load(f)

    async def update_user_memory(self, content: str) -> Dict:
        mem = await self.get_user_memory()
        mem.setdefault("facts", []).append(content)
        with open(self.path, "w") as f: json.dump(mem, f, indent=2)
        return {"status": "updated", "total_facts": len(mem["facts"])}
