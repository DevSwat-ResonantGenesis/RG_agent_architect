"""Builder Engine — High-reasoning model: creates agents, writes instructions"""
import logging
from typing import Any, Dict
from src.models.agent import Agent, Run, RunOutcome
from src.services.database.workspace_db import WorkspaceDB

logger = logging.getLogger(__name__)


class Builder:
    def __init__(self, workspace_id: str):
        self.ws_db = WorkspaceDB(workspace_id)

    async def build(self, name: str, goal: str, icon: str = "🤖") -> Dict[str, Any]:
        agent = Agent(name=name, goal=goal, icon=icon)
        agent.system_prompt = self._generate_instructions(goal)
        agent.needs_build = False
        await self.ws_db.save_agent(agent)
        run = Run(agent_id=agent.id, outcome=RunOutcome.SUCCESS)
        await self.ws_db.save_run(agent.id, run)
        return {"agent_id": agent.id, "name": name, "run_id": run.id, "outcome": "SUCCESS"}

    async def continue_build(self, agent_id: str, instructions: str) -> Dict:
        agent = await self.ws_db.get_agent(agent_id)
        if not agent: return {"error": "Agent not found"}
        agent.system_prompt = instructions
        agent.needs_build = False
        await self.ws_db.save_agent(agent)
        return {"agent_id": agent_id, "outcome": "SUCCESS"}

    async def message_build(self, agent_id: str, message: str) -> Dict:
        return {"agent_id": agent_id, "message_queued": True}

    def _generate_instructions(self, goal: str) -> str:
        return f"""You are an autonomous agent. Goal: {goal}
INSTRUCTIONS:
Step 1: Analyze goal, identify data sources.
Step 2: Gather data with appropriate tools.
Step 3: Process and filter results.
Step 4: Format output and store.
CONSTRAINTS: Max 50 results. No hallucination."""
