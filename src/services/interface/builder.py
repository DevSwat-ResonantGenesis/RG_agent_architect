"""Interface Builder — React app + API on agent's SQLite DB → public URL"""
from typing import Dict


class InterfaceBuilder:
    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id

    async def open_editor(self, agent_id: str) -> Dict:
        return {"agent_id": agent_id, "status": "editor_opened",
                "url": f"https://platform/interface/{agent_id}"}
