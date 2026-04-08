"""Builder Engine — High-reasoning model: creates agents via LLM + blockchain + wallet"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from src.core.llm_client import call_llm, REASONING_MODEL
from src.services.database.workspace_db import WorkspaceDB
from src.services.blockchain import chain_client
from src.services.billing import billing_client
from src.services.memory.memory_store import MemoryStore

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
    def __init__(self, workspace_id: str, user_id: str = ""):
        self.workspace_id = workspace_id
        self.user_id = user_id or workspace_id
        self.ws_db = WorkspaceDB(workspace_id)

    async def build(self, name: str, goal: str, icon: str = "🤖",
                    tools: list = None, max_loops: int = 30,
                    temperature: float = 0.5, model: str = "groq/llama-3.3-70b-versatile") -> Dict[str, Any]:
        agent_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # 1. Generate instructions via LLM
        instructions = await self._generate_instructions(goal, tools or [])

        # 2. Save agent to PostgreSQL
        await self.ws_db.save_agent(
            agent_id=agent_id, name=name, goal=goal, icon=icon,
            system_prompt=instructions, tools=tools or [],
            needs_build=False, max_loops=max_loops,
            temperature=temperature, model=model)

        # 3. Blockchain: identity hash first (needed for agent block)
        identity_result = await chain_client.register_agent_identity(agent_id, name, self.workspace_id, self.user_id)
        # Extract string hash from nested result
        if isinstance(identity_result, dict):
            identity_hash = (
                identity_result.get("hash", "")
                or identity_result.get("input_hash", "")
                or identity_result.get("identity_hash", "")
                or str(identity_result.get("domain", ""))
            )
            if isinstance(identity_hash, dict):
                identity_hash = identity_hash.get("input_hash", "") or str(identity_hash)
        else:
            identity_hash = str(identity_result) if identity_result else ""
        identity_hash = str(identity_hash)

        # 4. Parallel: on-chain registration + agent block (with hash) + wallet + hash sphere
        chain_results = await asyncio.gather(
            chain_client.register_on_chain(agent_id, name, self.user_id),
            chain_client.create_agent_block(agent_id, name, goal, self.user_id, agent_hash=identity_hash),
            chain_client.create_agent_wallet(agent_id, self.user_id),
            chain_client.create_agent_hash_sphere(agent_id, name),
            return_exceptions=True,
        )
        wallet_addr = ""
        if isinstance(chain_results[2], dict):
            wallet_addr = chain_results[2].get("address", "") or chain_results[2].get("wallet_address", "")

        # 4. Store build run
        await self.ws_db.save_run(
            run_id=run_id, agent_id=agent_id, outcome="SUCCESS",
            summary=f"Built agent: {name}", loop_count=1,
            started_at=now, finished_at=now)

        # 5. Store creation as agent memory/learning
        mem = MemoryStore(self.workspace_id, agent_id)
        await mem.store_agent_learning(
            f"Agent '{name}' created with goal: {goal}. Tools: {tools or []}. Identity: {identity_hash}",
            run_id=run_id)

        logger.info(f"[Builder] Created agent {agent_id}: {name} | chain={identity_hash[:16]}... wallet={wallet_addr[:16]}...")
        return {
            "agent_id": agent_id, "name": name, "run_id": run_id, "outcome": "SUCCESS",
            "identity_hash": identity_hash, "wallet_address": wallet_addr,
        }

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
