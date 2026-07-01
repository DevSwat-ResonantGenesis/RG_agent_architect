"""Runner Engine — Delegates execution to Agent Engine (full tool registry).

Primary path: POST /agents/{agent_id}/sessions on the Agent Engine, which
has 50+ real tools (web, file, code, email, GitHub, etc.) and SSE streaming.
Fallback: local LLM loop with basic tools if Agent Engine is unreachable.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from src.core.config import AGENT_ENGINE_URL
from src.core.llm_client import call_llm, DEFAULT_MODEL
from src.services.database.workspace_db import WorkspaceDB
from src.services.billing import billing_client
from src.services.memory.memory_store import MemoryStore

logger = logging.getLogger(__name__)

# Fallback tools — only used when Agent Engine delegation fails
_FALLBACK_TOOLS = [
    {"type": "function", "function": {"name": "web_search", "description": "Search the web",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "context": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "scrape_page", "description": "Scrape a web page",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "format": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "store_result", "description": "Store data in agent database",
        "parameters": {"type": "object", "properties": {"data": {"type": "string"}, "label": {"type": "string"}}, "required": ["data"]}}},
    {"type": "function", "function": {"name": "done", "description": "Signal task completion with summary",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}},
]


async def _exec_fallback_tool(name: str, args: Dict) -> Any:
    """Execute a tool locally — only for fallback mode."""
    if name == "web_search":
        from src.tools.builtin.web_search import web_search
        return await web_search(args.get("query", ""), args.get("context", ""))
    if name == "scrape_page":
        from src.tools.builtin.scrape_page import scrape_page
        return await scrape_page(args.get("url", ""), args.get("format", "markdown"))
    if name == "store_result":
        return {"stored": True, "label": args.get("label", "result")}
    if name == "done":
        return {"done": True, "summary": args.get("summary", "")}
    return {"error": f"Unknown tool: {name}"}


class Runner:
    def __init__(self, workspace_id: str, user_api_keys: Optional[Dict] = None):
        self.ws_db = WorkspaceDB(workspace_id)
        self._user_api_keys = user_api_keys

    async def run(self, agent_id: str, goal_override: Optional[str] = None, user_id: str = "") -> Dict[str, Any]:
        agent = await self.ws_db.get_agent(agent_id)
        if not agent:
            return {"error": "Agent not found"}
        if not agent.get("system_prompt"):
            return {"error": "No instructions — build first"}

        uid = user_id or self.ws_db.workspace_id
        credit_check = await billing_client.check_credits(uid)
        if not credit_check.get("has_credits", True):
            return {"error": "Insufficient credits", "credits": credit_check}

        goal = goal_override or agent.get("goal", agent.get("description", ""))

        # PRIMARY: Delegate to Agent Engine which has the full tool registry
        try:
            result = await self._run_via_agent_engine(agent_id, goal, uid)
            if result and not result.get("error"):
                # Store run summary as learning
                mem = MemoryStore(self.ws_db.workspace_id, agent_id)
                await mem.store_run_summary(
                    result.get("summary", ""), result.get("run_id", ""), agent_id)
                return result
            logger.warning(f"[Runner] Agent Engine delegation returned error: {result.get('error')}")
        except Exception as e:
            logger.warning(f"[Runner] Agent Engine delegation failed, falling back to local: {e}")

        # FALLBACK: Local LLM loop with basic tools
        return await self._run_local_fallback(agent, agent_id, goal, uid)

    async def _run_via_agent_engine(self, agent_id: str, goal: str, user_id: str) -> Dict[str, Any]:
        """Delegate execution to Agent Engine POST /agents/{agent_id}/sessions.

        Agent Engine has the full tool registry (50+ tools) and streams
        execution steps in real-time. This is the correct way to run agents.
        """
        payload = {
            "goal": goal,
            "status": "running",
        }
        headers = {**self.ws_db._headers}

        async with httpx.AsyncClient(timeout=180.0) as client:
            # Create session and start execution
            resp = await client.post(
                f"{AGENT_ENGINE_URL}/agents/{agent_id}/sessions",
                headers=headers, json=payload,
            )
            if resp.status_code not in (200, 201):
                return {"error": f"Agent Engine returned {resp.status_code}: {resp.text[:200]}"}

            session_data = resp.json()
            session_id = session_data.get("id", "")
            logger.info(f"[Runner] Agent Engine session created: {session_id}")

            # Poll for completion via session status
            import asyncio
            from src.core.config import POLL_MAX_ROUNDS, POLL_INTERVAL
            for _ in range(POLL_MAX_ROUNDS):
                await asyncio.sleep(POLL_INTERVAL)
                try:
                    status_resp = await client.get(
                        f"{AGENT_ENGINE_URL}/agents/sessions/{session_id}",
                        headers=headers,
                    )
                    if status_resp.status_code == 200:
                        sdata = status_resp.json()
                        status = sdata.get("status", "")
                        if status in ("completed", "failed", "cancelled"):
                            # Get steps for detailed report
                            steps = []
                            try:
                                steps_resp = await client.get(
                                    f"{AGENT_ENGINE_URL}/agents/sessions/{session_id}/steps",
                                    headers=headers,
                                )
                                if steps_resp.status_code == 200:
                                    steps = steps_resp.json()
                            except Exception:
                                pass

                            outcome = "SUCCESS" if status == "completed" else "FAIL"
                            summary = sdata.get("summary", sdata.get("result", ""))
                            if not summary and steps:
                                summary = "; ".join(
                                    s.get("output", s.get("result", ""))[:100]
                                    for s in (steps if isinstance(steps, list) else [])
                                    if s.get("output") or s.get("result")
                                )[:500]

                            tool_calls_count = len(steps) if isinstance(steps, list) else 0
                            return {
                                "agent_id": agent_id,
                                "run_id": session_id,
                                "outcome": outcome,
                                "summary": summary or f"Session {status}",
                                "loops": tool_calls_count,
                                "tool_calls_count": tool_calls_count,
                                "status": status,
                                "session_id": session_id,
                            }
                except Exception as e:
                    logger.debug(f"[Runner] Poll error: {e}")

            return {
                "agent_id": agent_id,
                "run_id": session_id,
                "outcome": "PARTIAL",
                "summary": f"Session {session_id} still running after polling timeout",
                "session_id": session_id,
            }

    async def _run_local_fallback(self, agent: Dict, agent_id: str, goal: str, user_id: str) -> Dict[str, Any]:
        """Fallback: run agent locally with basic tools when Agent Engine is unreachable."""
        logger.warning(f"[Runner] Using LOCAL fallback for {agent_id} — limited to basic tools")

        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        max_loops = agent.get("max_loops", 30)
        model = agent.get("model", DEFAULT_MODEL)
        temp = agent.get("temperature", 0.5)

        mem = MemoryStore(self.ws_db.workspace_id, agent_id)
        past = await mem.get_agent_memory()
        past_context = past.get("results", "") if isinstance(past, dict) else str(past)

        await self.ws_db.save_run(run_id=run_id, agent_id=agent_id, started_at=now)

        messages: List[Dict] = [
            {"role": "system", "content": agent["system_prompt"]},
        ]
        if past_context:
            messages.append({"role": "system", "content": f"Past learnings from previous runs:\n{str(past_context)[:8000]}"})
        messages.append({"role": "user", "content": f"Execute this goal now: {goal}"})
        all_tool_calls = []
        errors = []
        summary = ""
        outcome = "SUCCESS"
        loop = 0

        try:
            for loop in range(max_loops):
                resp = await call_llm(messages=messages, tools=_FALLBACK_TOOLS,
                                      model=model, temperature=temp, max_tokens=16000,
                                      user_api_keys=self._user_api_keys)
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

                    logger.info(f"[Runner:fallback] {agent_id} loop {loop}: {name}({list(args.keys())})")
                    result = await _exec_fallback_tool(name, args)
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
            logger.error(f"[Runner:fallback] {agent_id} failed: {e}")

        finished = datetime.now(timezone.utc)
        await self.ws_db.save_run(
            run_id=run_id, agent_id=agent_id, outcome=outcome,
            summary=summary, loop_count=loop + 1,
            started_at=now, finished_at=finished)

        await billing_client.deduct_credits(user_id, amount=loop + 1, reason=f"agent_run:{agent_id}")
        await mem.store_run_summary(summary, run_id, agent_id)

        logger.info(f"[Runner:fallback] {agent_id} run {run_id}: {outcome} in {loop + 1} loops")
        return {"agent_id": agent_id, "run_id": run_id, "outcome": outcome,
                "summary": summary, "loops": loop + 1, "tool_calls_count": len(all_tool_calls),
                "mode": "fallback"}
