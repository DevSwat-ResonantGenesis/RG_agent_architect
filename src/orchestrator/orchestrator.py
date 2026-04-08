"""Orchestrator — Main conversation loop with tool-calling"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from src.core.config import HISTORY_DEPTH, MAX_TOKENS, ORCHESTRATOR_MAX_ITERATIONS
from src.core.context import fetch_workspace_context
from src.core.llm_client import call_llm
from src.models.agent import OperationMode
from src.models.tools import ORCHESTRATOR_TOOLS
from src.orchestrator.tool_executor import ToolExecutor
from src.prompts.mode_classifier import classify_mode
from src.prompts.system_prompt import PLATFORM_PROMPT

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        self.tool_executor = ToolExecutor(workspace_id)
        self.history: List[Dict[str, str]] = []
        self.context: Optional[Dict[str, Any]] = None

    async def initialize_session(self):
        self.context = await fetch_workspace_context(self.workspace_id)
        return self.context

    async def handle_message(self, user_message: str) -> Dict[str, Any]:
        if not self.context:
            await self.initialize_session()
        agents_exist = bool(self.context.get("workspace", {}).get("agents", []))
        mode = classify_mode(user_message, agents_exist)
        self.history.append({"role": "user", "content": user_message})
        if len(self.history) > HISTORY_DEPTH * 2:
            self.history = self.history[-HISTORY_DEPTH * 2:]
        response = await self._run_loop(mode)
        self.history.append({"role": "assistant", "content": response.get("text", "")})
        return response

    async def _run_loop(self, mode: OperationMode) -> Dict[str, Any]:
        text = ""
        tool_results = []
        for _ in range(ORCHESTRATOR_MAX_ITERATIONS):
            llm_resp = await self._call_llm(mode, tool_results)
            if llm_resp.get("text"):
                text += llm_resp["text"]
            calls = llm_resp.get("tool_calls", [])
            if not calls:
                break
            tool_results = []
            results = await asyncio.gather(
                *[self.tool_executor.execute(c["name"], c["arguments"]) for c in calls],
                return_exceptions=True,
            )
            for c, r in zip(calls, results):
                entry = {"tool": c["name"]}
                entry["error" if isinstance(r, Exception) else "result"] = str(r) if isinstance(r, Exception) else r
                tool_results.append(entry)
                if c["name"] == "present_options":
                    return {"text": text, "options": r, "mode": mode.value}
        return {"text": text, "mode": mode.value}

    async def _call_llm(self, mode, tool_results):
        messages = [{"role": "system", "content": PLATFORM_PROMPT}]
        for h in self.history:
            messages.append(h)
        if tool_results:
            messages.append({"role": "user", "content": json.dumps(tool_results)})
        try:
            resp = await call_llm(messages=messages, model="llama-3.3-70b-versatile")
            choice = resp.get("choices", [{}])[0]
            msg = choice.get("message", {})
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])
            parsed_calls = []
            for tc in (tool_calls or []):
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                parsed_calls.append({"name": fn.get("name", ""), "arguments": args})
            return {"text": content, "tool_calls": parsed_calls}
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return {"text": f"Error: {e}", "tool_calls": []}

    async def handle_run_event(self, event: Dict) -> Dict:
        outcome = event.get("outcome", "")
        etype = event.get("type", "")
        if etype == "build" and outcome == "SUCCESS":
            opts = ["Set up trigger", "Create UI", "Try autonomous run"]
            return {"text": "Agent built.", "options": opts}
        if etype == "run" and outcome == "SUCCESS":
            return {"text": "Run completed.", "options": ["Run again", "Make changes", "Set up schedule"]}
        if outcome in ("PARTIAL", "FAIL"):
            return {"text": f"{etype.title()} {outcome}.", "options": ["Fix issue", "Try different approach", "Show details"]}
        return {"text": "Event received.", "options": []}
