"""Runner Engine — Smaller model: follows instructions, executes agents"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from src.models.agent import Run, RunOutcome
from src.services.database.workspace_db import WorkspaceDB

logger = logging.getLogger(__name__)


class Runner:
    def __init__(self, workspace_id: str):
        self.ws_db = WorkspaceDB(workspace_id)

    async def run(self, agent_id: str, goal_override: Optional[str] = None) -> Dict[str, Any]:
        agent = await self.ws_db.get_agent(agent_id)
        if not agent: return {"error": "Agent not found"}
        if not agent.system_prompt: return {"error": "No instructions — build first"}
        run = Run(agent_id=agent_id, started_at=datetime.now(timezone.utc))
        try:
            for loop in range(agent.max_loops):
                run.loop_count = loop + 1
                # TODO: call LLM with system_prompt → tool calls → execute
                run.summary = f"Executed: {goal_override or agent.goal}"
                run.outcome = RunOutcome.SUCCESS
                break
            else:
                run.outcome = RunOutcome.PARTIAL
        except Exception as e:
            run.outcome = RunOutcome.FAIL
            run.errors.append(str(e))
        run.finished_at = datetime.now(timezone.utc)
        await self.ws_db.save_run(agent_id, run)
        return {"agent_id": agent_id, "run_id": run.id, "outcome": run.outcome.value,
                "summary": run.summary, "loops": run.loop_count}
