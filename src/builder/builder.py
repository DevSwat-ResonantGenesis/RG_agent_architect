"""Builder Engine — High-reasoning model: creates agents via LLM"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from src.core.llm_client import call_llm, REASONING_MODEL
from src.services.database.workspace_db import WorkspaceDB

logger = logging.getLogger(__name__)

BUILDER_SYSTEM = """You are an expert agent builder. Given a goal, generate precise step-by-step instructions for an autonomous agent.
Output ONLY the instruction block — no preamble, no explanation.
Format:
ROLE: (one-line role description)
GOAL: (restate the goal clearly)
STEPS:
1. (specific action with tool name if applicable)
2. ...
3. ...
4. ...
CONSTRAINTS:
- Maximum 50 results unless user specifies otherwise
- Always include source URLs for scraped/searched data
- Never hallucinate data — only use tool outputs
- Store results in agent database
OUTPUT FORMAT: (describe expected output structure)"""


class Builder:
    def __init__(self, workspace_id: str):
        self.ws_db = WorkspaceDB(workspace_id)

    async def build(self, name: str, goal: str, icon: str = "🤖",
                    tools: list = None, max_loops: int = 30,
                    temperature: float = 0.5, model: str = "groq/llama-3.3-70b-versatile") -> Dict[str, Any]:
        agent_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        instructions = await self._generate_instructions(goal, tools or [])

        await self.ws_db.save_agent(
            agent_id=agent_id, name=name, goal=goal, icon=icon,
            system_prompt=instructions, tools=tools or [],
            needs_build=False, max_loops=max_loops,
            temperature=temperature, model=model)

        await self.ws_db.save_run(
            run_id=run_id, agent_id=agent_id, outcome="SUCCESS",
            summary=f"Built agent: {name}", loop_count=1,
            started_at=now, finished_at=now)

        logger.info(f"[Builder] Created agent {agent_id}: {name}")
        return {"agent_id": agent_id, "name": name, "run_id": run_id, "outcome": "SUCCESS"}

    async def continue_build(self, agent_id: str, instructions: str) -> Dict:
        agent = await self.ws_db.get_agent(agent_id)
        if not agent:
            return {"error": "Agent not found"}
        await self.ws_db.save_agent(
            agent_id=agent_id, name=agent["name"], goal=agent["goal"],
            icon=agent.get("icon", "🤖"), system_prompt=instructions,
            tools=agent.get("tools", []), needs_build=False)
        return {"agent_id": agent_id, "outcome": "SUCCESS"}

    async def message_build(self, agent_id: str, message: str) -> Dict:
        agent = await self.ws_db.get_agent(agent_id)
        if not agent:
            return {"error": "Agent not found"}
        current = agent.get("system_prompt", "")
        resp = await call_llm(messages=[
            {"role": "system", "content": BUILDER_SYSTEM},
            {"role": "user", "content": f"Current instructions:\n{current}\n\nUser wants to change:\n{message}\n\nOutput the FULL updated instruction block."}
        ], model=REASONING_MODEL, max_tokens=2048)
        new_prompt = resp.get("choices", [{}])[0].get("message", {}).get("content", current)
        await self.ws_db.save_agent(
            agent_id=agent_id, name=agent["name"], goal=agent["goal"],
            system_prompt=new_prompt, tools=agent.get("tools", []), needs_build=False)
        return {"agent_id": agent_id, "outcome": "SUCCESS", "updated": True}

    async def _generate_instructions(self, goal: str, tools: list) -> str:
        tool_list = ", ".join(tools) if tools else "web_search, scrape_page"
        resp = await call_llm(messages=[
            {"role": "system", "content": BUILDER_SYSTEM},
            {"role": "user", "content": f"Goal: {goal}\nAvailable tools: {tool_list}"}
        ], model=REASONING_MODEL, max_tokens=2048, temperature=0.4)
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            content = f"ROLE: Autonomous agent\nGOAL: {goal}\nSTEPS:\n1. Use {tool_list} to gather data\n2. Process results\n3. Store output"
        return content
