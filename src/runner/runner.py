"""Runner Engine — Executes agents via LLM loop with real tool calls + billing + learning"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.llm_client import call_llm, DEFAULT_MODEL
from src.services.database.workspace_db import WorkspaceDB
from src.services.billing import billing_client
from src.services.memory.memory_store import MemoryStore
from src.tools.builtin.web_search import web_search
from src.tools.builtin.scrape_page import scrape_page

logger = logging.getLogger(__name__)

RUNNER_TOOLS = [
    {"type": "function", "function": {"name": "web_search", "description": "Search the web using Perplexity AI",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "context": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "scrape_page", "description": "Scrape a web page via Firecrawl",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "format": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "store_result", "description": "Store data in agent database",
        "parameters": {"type": "object", "properties": {"data": {"type": "string"}, "label": {"type": "string"}}, "required": ["data"]}}},
    {"type": "function", "function": {"name": "done", "description": "Signal task completion with summary",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}},
]


async def _exec_tool(name: str, args: Dict) -> Any:
    if name == "web_search":
        return await web_search(args.get("query", ""), args.get("context", ""))
    if name == "scrape_page":
        return await scrape_page(args.get("url", ""), args.get("format", "markdown"))
    if name == "store_result":
        return {"stored": True, "label": args.get("label", "result")}
    if name == "done":
        return {"done": True, "summary": args.get("summary", "")}
    return {"error": f"Unknown tool: {name}"}


class Runner:
    def __init__(self, workspace_id: str):
        self.ws_db = WorkspaceDB(workspace_id)

    async def run(self, agent_id: str, goal_override: Optional[str] = None, user_id: str = "") -> Dict[str, Any]:
        agent = await self.ws_db.get_agent(agent_id)
        if not agent:
            return {"error": "Agent not found"}
        if not agent.get("system_prompt"):
            return {"error": "No instructions — build first"}

        # Check credits before running
        uid = user_id or self.ws_db.workspace_id
        credit_check = await billing_client.check_credits(uid)
        if not credit_check.get("has_credits", True):
            return {"error": "Insufficient credits", "credits": credit_check}

        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        max_loops = agent.get("max_loops", 30)
        model = agent.get("model", DEFAULT_MODEL)
        temp = agent.get("temperature", 0.5)
        goal = goal_override or agent.get("goal", "")

        # Recall past learnings for this agent
        mem = MemoryStore(self.ws_db.workspace_id, agent_id)
        past = await mem.get_agent_memory()
        past_context = past.get("results", "") if isinstance(past, dict) else str(past)

        await self.ws_db.save_run(run_id=run_id, agent_id=agent_id, started_at=now)

        messages: List[Dict] = [
            {"role": "system", "content": agent["system_prompt"]},
        ]
        if past_context:
            messages.append({"role": "system", "content": f"Past learnings from previous runs:\n{str(past_context)[:2000]}"})
        messages.append({"role": "user", "content": f"Execute this goal now: {goal}"})
        all_tool_calls = []
        errors = []
        summary = ""
        outcome = "SUCCESS"
        loop = 0

        try:
            for loop in range(max_loops):
                resp = await call_llm(messages=messages, tools=RUNNER_TOOLS,
                                      model=model, temperature=temp, max_tokens=4096)
                choice = resp.get("choices", [{}])[0]
                msg = choice.get("message", {})
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls") or []

                if content:
                    messages.append({"role": "assistant", "content": content})

                if not tool_calls:
                    summary = content or f"Completed in {loop + 1} loops"
                    break

                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}

                    logger.info(f"[Runner] {agent_id} loop {loop}: {name}({list(args.keys())})")
                    result = await _exec_tool(name, args)
                    all_tool_calls.append({"tool": name, "args": args, "result_preview": str(result)[:200]})

                    if name == "done":
                        summary = args.get("summary", str(result))
                        break

                    messages.append({"role": "assistant", "content": None,
                                     "tool_calls": [{"id": tc.get("id", ""), "type": "function",
                                                      "function": {"name": name, "arguments": fn.get("arguments", "{}")}}]})
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                     "content": json.dumps(result) if isinstance(result, dict) else str(result)})

                if summary:
                    break
            else:
                outcome = "PARTIAL"
                summary = f"Reached max loops ({max_loops})"
        except Exception as e:
            outcome = "FAIL"
            errors.append(str(e))
            summary = f"Error: {e}"
            logger.error(f"[Runner] {agent_id} failed: {e}")

        finished = datetime.now(timezone.utc)
        await self.ws_db.save_run(
            run_id=run_id, agent_id=agent_id, outcome=outcome,
            summary=summary, loop_count=loop + 1, tool_calls=all_tool_calls,
            tokens_used=0, errors=errors, started_at=now, finished_at=finished)

        # Deduct credits after run
        await billing_client.deduct_credits(uid, amount=loop + 1, reason=f"agent_run:{agent_id}")

        # Store run summary as learning for future runs
        await mem.store_run_summary(summary, run_id, agent_id)

        logger.info(f"[Runner] {agent_id} run {run_id}: {outcome} in {loop + 1} loops")
        return {"agent_id": agent_id, "run_id": run_id, "outcome": outcome,
                "summary": summary, "loops": loop + 1, "tool_calls_count": len(all_tool_calls)}
