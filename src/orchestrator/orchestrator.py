"""Orchestrator — Main conversation loop with proper tool-calling protocol"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from src.core.config import HISTORY_DEPTH
from src.core.context import fetch_workspace_context
from src.core.llm_client import call_llm
from src.models.agent import OperationMode
from src.models.tools import ORCHESTRATOR_TOOLS
from src.orchestrator.tool_executor import ToolExecutor
from src.prompts.mode_classifier import classify_mode
from src.prompts.system_prompt import PLATFORM_PROMPT

logger = logging.getLogger(__name__)

MAX_TOOL_LOOPS = 5


class Orchestrator:
    def __init__(self, workspace_id: str, user_id: str = ""):
        self.workspace_id = workspace_id
        self.user_id = user_id or workspace_id
        self.tool_executor = ToolExecutor(workspace_id, user_id=self.user_id)
        self.history: List[Dict] = []
        self.context: Optional[Dict[str, Any]] = None

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

        for iteration in range(MAX_TOOL_LOOPS):
            try:
                resp = await call_llm(
                    messages=messages,
                    tools=ORCHESTRATOR_TOOLS,
                    model="groq/llama-3.3-70b-versatile",
                )
            except Exception as e:
                logger.error(f"LLM call failed iteration {iteration}: {e}")
                return {"text": final_text or f"Error: {e}", "mode": mode.value}

            choice = resp.get("choices", [{}])[0]
            msg = choice.get("message", {})
            content = msg.get("content", "")
            raw_tool_calls = msg.get("tool_calls") or []

            if content:
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
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                logger.warning(f"[Orch] tool: {name}({list(args.keys())})")
                try:
                    result = await self.tool_executor.execute(name, args)
                    logger.warning(f"[Orch] result: {str(result)[:200]}")
                except Exception as e:
                    logger.error(f"[Orch] tool {name} exception: {e}")
                    result = {"error": str(e)}

                if name == "present_options":
                    if not final_text.strip():
                        # Generate summary of actions taken before showing options
                        try:
                            summary_resp = await call_llm(
                                messages=messages + [{"role": "user", "content": "Briefly summarize what you just did (1-2 sentences). Be natural."}],
                                model="groq/llama-3.3-70b-versatile",
                            )
                            sc = summary_resp.get("choices", [{}])[0].get("message", {}).get("content", "")
                            if sc:
                                final_text = sc
                        except Exception:
                            pass
                    return {"text": final_text, "options": result, "mode": mode.value}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": json.dumps(result, default=str) if not isinstance(result, str) else result,
                })

            # Loop continues — next iteration calls LLM with tool results

        # If text is still empty (Groq doesn't emit content with tool_calls),
        # make one final call WITHOUT tools to force a natural text response
        if not final_text.strip():
            try:
                summary_resp = await call_llm(
                    messages=messages + [{"role": "user", "content": "Summarize what you just did in 1-2 sentences. Be natural, concise."}],
                    model="groq/llama-3.3-70b-versatile",
                )
                sc = summary_resp.get("choices", [{}])[0].get("message", {}).get("content", "")
                if sc:
                    final_text = sc
            except Exception:
                pass

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
