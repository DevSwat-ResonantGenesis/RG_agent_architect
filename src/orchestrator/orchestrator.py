"""Orchestrator — Main conversation loop with SSE streaming and verification.

Supports two modes:
  - handle_message(): synchronous JSON response (backward compat)
  - handle_message_stream(): async generator yielding SSE progress events
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

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

# Tools that are "terminal" — after success, get summary and return
TERMINAL_TOOLS = {"build_agent", "delete_agent", "modify_agent"}


class Orchestrator:
    def __init__(self, workspace_id: str, user_id: str = ""):
        self.workspace_id = workspace_id
        self.user_id = user_id or workspace_id
        self.tool_executor = ToolExecutor(workspace_id, user_id=self.user_id)
        self.history: List[Dict] = []
        self.context: Optional[Dict[str, Any]] = None
        self.safety = get_safety()
        self._progress_queue: Optional[asyncio.Queue] = None

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

    async def _emit_progress(self, event_type: str, data: Dict):
        """Push a progress event to the SSE queue if streaming."""
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        logger.info(f"[Orch] SSE: {event_type} — {str(data)[:120]}")
        if self._progress_queue:
            await self._progress_queue.put(event)

    # ── Synchronous API (backward compat) ──

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
        await self.initialize_session()
        return response

    # ── Streaming API (SSE) ──

    async def handle_message_stream(
        self, user_message: str
    ) -> AsyncIterator[Dict[str, Any]]:
        """Async generator that yields SSE events during orchestration."""
        self._progress_queue = asyncio.Queue()

        if not self.context:
            await self.initialize_session()

        agents_exist = bool(self.context.get("workspace", {}).get("agents", []))
        mode = classify_mode(user_message, agents_exist)
        self.history.append({"role": "user", "content": user_message})
        if len(self.history) > HISTORY_DEPTH * 2:
            self.history = self.history[-HISTORY_DEPTH * 2:]

        yield {"type": "session_start", "mode": mode.value,
               "agents_count": len(self.context.get("workspace", {}).get("agents", []))}

        # Run the loop in a task so we can yield events as they arrive
        result_future: asyncio.Future = asyncio.get_event_loop().create_future()

        async def _run():
            try:
                r = await self._run_loop(mode)
                result_future.set_result(r)
            except Exception as e:
                result_future.set_exception(e)
            finally:
                await self._progress_queue.put(None)  # Sentinel

        task = asyncio.create_task(_run())

        # Yield progress events as they arrive
        while True:
            event = await self._progress_queue.get()
            if event is None:
                break
            yield event

        # Yield final result
        try:
            response = result_future.result()
            self.history.append({"role": "assistant", "content": response.get("text", "")})
            await self.initialize_session()
            yield {"type": "complete", "response": response}
        except Exception as e:
            yield {"type": "error", "error": str(e)}

        self._progress_queue = None

    # ── Core loop ──

    async def _run_loop(self, mode: OperationMode) -> Dict[str, Any]:
        context_block = self._build_context_block()
        system_content = PLATFORM_PROMPT
        if context_block:
            system_content += f"\n<context>\n{context_block}\n</context>"

        messages = [{"role": "system", "content": system_content}]
        messages.extend(self.history)
        final_text = ""
        actions_taken = []

        for iteration in range(MAX_TOOL_LOOPS):
            await self._emit_progress("thinking", {
                "iteration": iteration,
                "message": "Analyzing your request..." if iteration == 0 else "Processing next step..."
            })

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
                await self._emit_progress("error", {"message": f"LLM call failed: {e}"})
                return {"text": final_text or f"Error: {e}", "mode": mode.value}

            choice = resp.get("choices", [{}])[0]
            msg = choice.get("message", {})
            content = msg.get("content", "")
            raw_tool_calls = msg.get("tool_calls") or []

            if content:
                is_safe, safety_error = self.safety.check_llm_response(content)
                if not is_safe:
                    logger.error(f"[Orch] Safety blocked LLM response: {safety_error}")
                    content = f"[Safety blocked: {safety_error}]"
                final_text += content
                await self._emit_progress("text", {"content": content})

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
                await self._emit_progress("tool_call", {
                    "tool": name,
                    "args_keys": list(args.keys()),
                    "message": _tool_progress_message(name, args),
                })

                # Safety check before execution
                is_safe, safety_error = self.safety.check_tool_args(name, args)
                if not is_safe:
                    logger.error(f"[Orch] Safety blocked {name}: {safety_error}")
                    result = {"error": f"Safety blocked: {safety_error}"}
                    actions_taken.append({"tool": name, "args": args, "result": result, "blocked": True})
                    messages.append({
                        "role": "tool", "tool_call_id": tc_id,
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

                # Emit tool result
                result_preview = str(result)[:300] if not isinstance(result, dict) else json.dumps(result, default=str)[:300]
                is_error = isinstance(result, dict) and (result.get("error") or result.get("outcome") == "FAIL")
                await self._emit_progress("tool_result", {
                    "tool": name,
                    "success": not is_error,
                    "preview": result_preview,
                    "message": _tool_result_message(name, result),
                })

                # Terminal tools: break loop, get summary
                if name in TERMINAL_TOOLS and isinstance(result, dict) and not result.get("error") and result.get("outcome") != "FAIL":
                    messages.append({
                        "role": "tool", "tool_call_id": tc_id,
                        "content": json.dumps(result, default=str) if not isinstance(result, str) else result,
                    })
                    await self._emit_progress("summarizing", {"message": "Generating summary..."})
                    try:
                        summary_resp = await call_llm(
                            messages=messages,
                            model="groq/llama-3.3-70b-versatile",
                            temperature=0.5,
                            max_tokens=MAX_TOKENS,
                        )
                        summary_text = summary_resp.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if summary_text:
                            final_text = summary_text
                    except Exception:
                        pass
                    if not final_text.strip():
                        final_text = _summarize_actions(actions_taken)
                    return {"text": final_text, "mode": mode.value,
                            "actions": actions_taken}

                # If terminal tool FAILED, let the LLM know and continue
                if name in TERMINAL_TOOLS and isinstance(result, dict) and (result.get("error") or result.get("outcome") == "FAIL"):
                    error_msg = result.get("error", "Operation failed")
                    messages.append({
                        "role": "tool", "tool_call_id": tc_id,
                        "content": json.dumps({"error": error_msg, "outcome": "FAIL"}, default=str),
                    })
                    await self._emit_progress("error", {
                        "tool": name,
                        "message": f"Failed: {error_msg}",
                    })
                    # Let LLM generate error response
                    try:
                        err_resp = await call_llm(
                            messages=messages,
                            model="groq/llama-3.3-70b-versatile",
                            temperature=0.5,
                            max_tokens=MAX_TOKENS,
                        )
                        err_text = err_resp.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if err_text:
                            final_text = err_text
                    except Exception:
                        pass
                    if not final_text.strip():
                        final_text = f"Failed to {name}: {error_msg}"
                    return {"text": final_text, "mode": mode.value,
                            "actions": actions_taken, "error": error_msg}

                if name == "present_options":
                    if not final_text.strip():
                        final_text = _summarize_actions(actions_taken)
                    return {"text": final_text, "options": result, "mode": mode.value}

                messages.append({
                    "role": "tool", "tool_call_id": tc_id,
                    "content": json.dumps(result, default=str) if not isinstance(result, str) else result,
                })

        if not final_text.strip() and actions_taken:
            final_text = _summarize_actions(actions_taken)

        return {"text": final_text, "mode": mode.value, "actions": actions_taken}

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


def _tool_progress_message(name: str, args: Dict) -> str:
    """Human-readable message for tool call start."""
    if name == "build_agent":
        return f"Building agent '{args.get('name', 'new agent')}'..."
    if name == "modify_agent":
        return f"Modifying agent {args.get('agent_id', '')[:8]}..."
    if name == "run_agent":
        return f"Running agent {args.get('agent_id', '')[:8]}..."
    if name == "delete_agent":
        return f"Deleting agent {args.get('agent_id', '')[:8]}..."
    if name == "set_trigger":
        return f"Setting {args.get('interval', 'daily')} schedule..."
    if name == "check_integrations":
        return "Checking connected integrations..."
    if name == "workspace_snapshot":
        return "Loading workspace..."
    return f"Executing {name}..."


def _tool_result_message(name: str, result: Any) -> str:
    """Human-readable message for tool result."""
    if not isinstance(result, dict):
        return f"{name} completed"
    err = result.get("error")
    if err:
        return f"{name} failed: {err}"
    if name == "build_agent":
        verified = result.get("verified", False)
        tools_ok = result.get("tools_all_ok", False)
        return (f"Agent '{result.get('name', '')}' created"
                f"{' and verified' if verified else ''}"
                f"{' — all tools working' if tools_ok else ''}")
    if name == "modify_agent":
        return f"Agent modified — tools: {result.get('tools', [])}"
    if name == "run_agent":
        return f"Run complete: {result.get('outcome', '')} in {result.get('loops', 0)} loops"
    if name == "set_trigger":
        return f"Schedule set: {result.get('interval', 'daily')}"
    return f"{name} completed"


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
                verified = " Verified in database." if r.get("verified") else ""
                tools_ok = " All tools tested OK." if r.get("tools_all_ok") else ""
                parts.append(f"Built **{name}** — registered on blockchain.{verified}{tools_ok}")
        elif tool == "modify_agent":
            if err:
                parts.append(f"Tried to modify agent but hit an error: {err}")
            else:
                parts.append(f"Modified agent — updated tools: {r.get('tools', [])}")
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
            if err:
                parts.append(f"Tried to delete agent but hit an error: {err}")
            else:
                status = r.get("status", "")
                if status == "archived":
                    parts.append("Archived the agent (hidden from active list).")
                elif status == "already_archived":
                    parts.append("Agent was already archived.")
                else:
                    parts.append("Deleted the agent.")
        elif tool == "stop_run":
            parts.append("Stopped the run.")
        elif tool == "present_options":
            pass
    return " ".join(parts) if parts else ""
