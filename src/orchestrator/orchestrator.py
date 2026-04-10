"""Orchestrator — Main conversation loop with proper tool-calling protocol"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from src.core.config import HISTORY_DEPTH, ORCHESTRATOR_MAX_ITERATIONS, MAX_TOKENS
from src.core.context import fetch_workspace_context
from src.core.llm_client import call_llm
from src.models.agent import OperationMode
from src.models.tools import ORCHESTRATOR_TOOLS
from src.orchestrator.tool_executor import ToolExecutor
from src.orchestrator.safety import get_safety
from src.prompts.mode_classifier import classify_mode
from src.prompts.system_prompt import PLATFORM_PROMPT

logger = logging.getLogger(__name__)

MAX_TOOL_LOOPS = ORCHESTRATOR_MAX_ITERATIONS


class Orchestrator:
    def __init__(self, workspace_id: str, user_id: str = ""):
        self.workspace_id = workspace_id
        self.user_id = user_id or workspace_id
        self.tool_executor = ToolExecutor(workspace_id, user_id=self.user_id)
        self.history: List[Dict] = []
        self.context: Optional[Dict[str, Any]] = None
        self.safety = get_safety()

    async def initialize_session(self):
        self.context = await fetch_workspace_context(self.workspace_id, user_id=self.user_id)
        return self.context

    def _build_context_block(self) -> str:
        """Build a context summary so the LLM knows the current workspace state."""
        if not self.context:
            return ""
        parts = []
        ws = self.context.get("workspace", {})
        agents = ws.get("agents", [])
        if agents:
            lines = []
            for a in agents:
                lines.append(f"  {a.get('icon','🤖')} {a['name']} (id:{a['id']}) — {a.get('goal','')}")
            parts.append("AGENTS:\n" + "\n".join(lines))
        else:
            parts.append("WORKSPACE: empty, no agents yet.")

        tools = self.context.get("tools", [])
        builtin = [t["name"] for t in tools if t.get("category") == "builtin"]
        if builtin:
            parts.append(f"TOOLS: {', '.join(builtin)}")

        integrations = self.context.get("integrations", {})
        connected = integrations.get("connected", [])
        if connected:
            parts.append(f"CONNECTED: {', '.join(connected)}")

        economy = self.context.get("economy", {})
        if economy:
            parts.append(f"PLAN: {economy.get('plan','free')} | CREDITS: {economy.get('credits_remaining',0)}")

        return "\n".join(parts)

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
        # Refresh context after actions
        await self.initialize_session()
        return response

    async def _run_loop(self, mode: OperationMode) -> Dict[str, Any]:
        context_block = self._build_context_block()
        system_content = PLATFORM_PROMPT
        if context_block:
            system_content += f"\n<context>\n{context_block}\n</context>"

        messages = [{"role": "system", "content": system_content}]
        messages.extend(self.history)
        final_text = ""
        actions_taken = []  # Track what we did for natural summary

        for iteration in range(MAX_TOOL_LOOPS):
            try:
                resp = await call_llm(
                    messages=messages,
                    tools=ORCHESTRATOR_TOOLS,
                    model="groq/llama-3.3-70b-versatile",
                    temperature=0.5,
                    max_tokens=MAX_TOKENS,
                )
            except Exception as e:
                logger.error(f"LLM call failed iteration {iteration}: {e}")
                return {"text": final_text or f"Error: {e}", "mode": mode.value}

            choice = resp.get("choices", [{}])[0]
            msg = choice.get("message", {})
            content = msg.get("content", "")
            raw_tool_calls = msg.get("tool_calls") or []

            # Safety check for LLM response content
            if content:
                is_safe, safety_error = self.safety.check_llm_response(content)
                if not is_safe:
                    logger.error(f"[Orch] Safety blocked LLM response: {safety_error}")
                    content = f"[Safety blocked: {safety_error}]"
                final_text += content

            if not raw_tool_calls:
                break

            assistant_msg = {"role": "assistant", "content": content or None}
            assistant_msg["tool_calls"] = raw_tool_calls
            messages.append(assistant_msg)

            for tc in raw_tool_calls:
                tc_id = tc.get("id", "")
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments", "{}")) or {}
                except (json.JSONDecodeError, TypeError):
                    args = {}

                logger.warning(f"[Orch] tool: {name}({list(args.keys())})")
                
                # Safety check before execution
                is_safe, safety_error = self.safety.check_tool_args(name, args)
                if not is_safe:
                    logger.error(f"[Orch] Safety blocked {name}: {safety_error}")
                    result = {"error": f"Safety blocked: {safety_error}"}
                    actions_taken.append({"tool": name, "args": args, "result": result, "blocked": True})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps(result, default=str),
                    })
                    continue
                
                try:
                    result = await self.tool_executor.execute(name, args)
                    logger.warning(f"[Orch] result: {str(result)[:200]}")
                except Exception as e:
                    logger.error(f"[Orch] tool {name} exception: {e}")
                    result = {"error": str(e)}

                actions_taken.append({"tool": name, "args": args, "result": result})

                if name == "present_options":
                    if not final_text.strip():
                        final_text = _summarize_actions(actions_taken)
                    return {"text": final_text, "options": result, "mode": mode.value}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": json.dumps(result, default=str) if not isinstance(result, str) else result,
                })

        if not final_text.strip() and actions_taken:
            final_text = _summarize_actions(actions_taken)

        return {"text": final_text, "mode": mode.value}

    async def handle_run_event(self, event: Dict) -> Dict:
        outcome = event.get("outcome", "")
        etype = event.get("type", "")
        if etype == "build" and outcome == "SUCCESS":
            return {"text": "Agent built.", "options": ["Set up trigger", "Try autonomous run"]}
        if etype == "run" and outcome == "SUCCESS":
            return {"text": "Run completed.", "options": ["Run again", "Set up schedule"]}
        if outcome in ("PARTIAL", "FAIL"):
            return {"text": f"{etype.title()} {outcome}.", "options": ["Fix issue", "Show details"]}
        return {"text": "Event received.", "options": []}


def _summarize_actions(actions: list) -> str:
    """Build a natural text summary from the actions the LLM took."""
    parts = []
    for a in actions:
        tool = a["tool"]
        r = a.get("result", {})
        if not isinstance(r, dict):
            continue
        err = r.get("error", "")
        if tool == "build_agent":
            name = r.get("name", "agent")
            if err:
                parts.append(f"Tried to build **{name}** but hit an error: {err}")
            else:
                parts.append(f"Built **{name}** — registered on blockchain with wallet and identity hash.")
        elif tool == "continue_build":
            parts.append("Refined the agent's instructions.")
        elif tool == "set_trigger":
            interval = r.get("interval", "daily")
            parts.append(f"Set up a **{interval}** schedule.")
        elif tool == "run_agent":
            summary = r.get("summary", "")
            loops = r.get("loops", 0)
            if err:
                parts.append(f"Run failed: {err}")
            else:
                parts.append(f"Ran the agent ({loops} steps). {summary}" if summary else f"Ran the agent ({loops} steps).")
        elif tool == "delete_agent":
            parts.append("Deleted the agent.")
        elif tool == "stop_run":
            parts.append("Stopped the run.")
        elif tool == "present_options":
            pass
    return " ".join(parts) if parts else ""
