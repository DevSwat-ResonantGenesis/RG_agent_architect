"""Orchestrator — Main conversation loop with SSE streaming and verification.

Supports two modes:
  - handle_message(): synchronous JSON response (backward compat)
  - handle_message_stream(): async generator yielding SSE progress events

Build intent detection:
  When a user wants to build/create an agent, the orchestrator uses BuildPipeline
  for a structured multi-step interactive workflow instead of a single LLM call.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from src.core.config import HISTORY_DEPTH, ORCHESTRATOR_MAX_ITERATIONS, MAX_TOKENS
from src.core.context import fetch_workspace_context
from src.core.llm_client import call_llm
from src.models.agent import OperationMode
from src.models.tools import ORCHESTRATOR_TOOLS
from src.orchestrator.build_pipeline import BuildPipeline
from src.orchestrator.tool_executor import ToolExecutor
from src.orchestrator.safety import get_safety
from src.orchestrator.tool_classifier import architect_tool_classifier, fallback_get_tools, TOOL_GROUPS
from src.prompts.mode_classifier import classify_mode
from src.prompts.router import get_router
from src.services.auth.integration_client import get_user_api_keys

logger = logging.getLogger(__name__)

MAX_TOOL_LOOPS = ORCHESTRATOR_MAX_ITERATIONS

# Tools that are "terminal" — after success, get summary and return
# NOTE: delete_agent is NOT terminal so the LLM can loop and delete multiple agents
TERMINAL_TOOLS = {"build_agent", "modify_agent"}

# Patterns that indicate user wants to BUILD an agent
_BUILD_INTENT_PATTERNS = [
    r"(?:build|create|make)\s+(?:me\s+)?(?:an?\s+)?(?:agent|bot)",
    r"(?:build|create|make)\s+(?:an?\s+)?(?:agent|bot)\s+(?:that|which|to|for)",
    r"(?:i\s+(?:want|need)\s+(?:to\s+)?(?:build|create|make)|set\s+up)\s+(?:an?\s+)?(?:agent|bot)",
    r"(?:agent|bot)\s+(?:that|which|to)\s+(?:can|will|should)",
]


def _is_build_intent(message: str) -> bool:
    """Detect if user wants to build/create an agent."""
    msg_lower = message.lower().strip()
    return any(re.search(p, msg_lower) for p in _BUILD_INTENT_PATTERNS)



class Orchestrator:
    def __init__(self, workspace_id: str, user_id: str = ""):
        self.workspace_id = workspace_id
        self.user_id = user_id or workspace_id
        self.tool_executor = ToolExecutor(workspace_id, user_id=self.user_id)
        self.history: List[Dict] = []
        self.context: Optional[Dict[str, Any]] = None
        self.safety = get_safety()
        self._progress_queue: Optional[asyncio.Queue] = None
        self._user_api_keys: Optional[Dict[str, str]] = None
        # Build pipeline state — persists across messages
        self._pipeline: Optional[BuildPipeline] = None
        self._pipeline_phase: Optional[str] = None  # waiting_confirm, waiting_prompt_review, etc.
        self._pipeline_plan: Optional[Dict] = None

    async def initialize_session(self):
        self.context = await fetch_workspace_context(self.workspace_id, user_id=self.user_id)
        # Fetch BYOK keys so LLM calls use user's own API keys when available
        if self._user_api_keys is None:
            try:
                keys_resp = await get_user_api_keys(self.user_id)
                raw_keys = keys_resp.get("keys", [])
                byok = {}
                for k in raw_keys:
                    provider = (k.get("provider") or "").lower()
                    api_key = k.get("api_key") or k.get("key") or ""
                    if provider and api_key:
                        byok[provider] = api_key
                self._user_api_keys = byok if byok else None
                if byok:
                    logger.info(f"[Orch] Loaded BYOK keys for providers: {list(byok.keys())}")
            except Exception as e:
                logger.warning(f"[Orch] Failed to load BYOK keys: {e}")
                self._user_api_keys = None
        return self.context

    def _build_context_block(self) -> str:
        """Build a context summary so the LLM knows the current workspace state.
        
        The context block is THE source of truth. The LLM should answer
        questions from this data without needing to call workspace_snapshot.
        """
        if not self.context:
            return ""
        parts = []
        ws = self.context.get("workspace", {})
        agents = ws.get("agents", [])

        # Prominent count header so LLM can answer "how many" instantly
        parts.append(f"TOTAL AGENTS: {len(agents)}")

        if agents:
            lines = []
            default_icon = "🤖"
            for a in agents:
                icon = a.get('icon', default_icon)
                name = a.get('name', '?')
                aid = a.get('id', '?')
                goal = a.get('goal', 'no goal')
                status = a.get('status', 'active')
                tools_list = a.get('tools', [])
                tool_count = len(tools_list) if isinstance(tools_list, list) else 0
                lines.append(
                    f"  {icon} {name} (id:{aid}) — {goal} | tools:{tool_count} | status:{status}"
                )
            parts.append("AGENTS:\n" + "\n".join(lines))
        else:
            parts.append("WORKSPACE: empty, no agents yet.")

        tools = self.context.get("tools", [])
        builtin = [t["name"] for t in tools if t.get("category") == "builtin"]
        if builtin:
            parts.append(f"AVAILABLE TOOLS: {', '.join(builtin)}")

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
        q = self._progress_queue
        if q:
            try:
                await q.put(event)
            except Exception:
                pass

    # ── Synchronous API (backward compat) ──

    async def handle_message(self, user_message: str) -> Dict[str, Any]:
        if not self.context:
            await self.initialize_session()
        self.tool_executor._user_api_keys = self._user_api_keys
        agents_exist = bool(self.context.get("workspace", {}).get("agents", []))
        mode = classify_mode(user_message, agents_exist)
        self.history.append({"role": "user", "content": user_message})
        if len(self.history) > HISTORY_DEPTH * 2:
            self.history = self.history[-HISTORY_DEPTH * 2:]

        # Check if this is a build pipeline flow
        if self._pipeline_phase and self._pipeline:
            response = await self._continue_build_pipeline(user_message)
        elif _is_build_intent(user_message):
            response = await self._start_build_pipeline(user_message)
        else:
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
        self.tool_executor._user_api_keys = self._user_api_keys

        agents_exist = bool(self.context.get("workspace", {}).get("agents", []))
        mode = classify_mode(user_message, agents_exist)
        self.history.append({"role": "user", "content": user_message})
        if len(self.history) > HISTORY_DEPTH * 2:
            self.history = self.history[-HISTORY_DEPTH * 2:]

        yield {"type": "session_start", "mode": mode.value,
               "agents_count": len(self.context.get("workspace", {}).get("agents", []))}

        # Decide which flow to run
        is_pipeline = False
        if self._pipeline_phase and self._pipeline:
            is_pipeline = True
            run_fn = self._continue_build_pipeline(user_message)
        elif _is_build_intent(user_message):
            is_pipeline = True
            run_fn = self._start_build_pipeline(user_message)
        else:
            run_fn = self._run_loop(mode)

        result_future: asyncio.Future = asyncio.get_event_loop().create_future()
        queue_ref = self._progress_queue  # local ref survives cleanup

        async def _run():
            try:
                r = await run_fn
                result_future.set_result(r)
            except Exception as e:
                result_future.set_exception(e)
            finally:
                if queue_ref is not None:
                    await queue_ref.put(None)  # Sentinel

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

    # ── Build Pipeline (autonomous end-to-end workflow) ──

    async def _start_build_pipeline(self, user_message: str) -> Dict[str, Any]:
        """Full autonomous pipeline: research → plan → verify → prompt → build → test → offers.

        Runs ALL phases in one continuous stream with no stops.
        Streams formatted progress as one rich message.
        """
        from src.services.database.workspace_db import WorkspaceDB
        ws_db = WorkspaceDB(self.workspace_id, self.user_id)

        pipeline = BuildPipeline(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            user_message=user_message,
            emit=self._emit_progress,
            ws_db=ws_db,
            user_api_keys=self._user_api_keys,
        )
        self._pipeline = pipeline
        text_parts = []

        # ── Phase 1: RESEARCH ──
        research = await pipeline.run_phase_1_research()
        credits_info = research.get("credits", {})
        connected = research.get("integrations", {})
        connected_list = connected.get("connected", []) if isinstance(connected, dict) else []
        existing = research.get("existing_agents", [])

        text_parts.append("🔍 **Research complete**")
        text_parts.append(f"  - Credits: {credits_info.get('remaining', 'available')}")
        text_parts.append(f"  - Integrations: {len(connected_list)} connected")
        text_parts.append(f"  - Existing agents: {len(existing)}")
        for w in research.get("warnings", []):
            text_parts.append(f"  - ⚠️ {w}")
        await self._emit_progress("text", {"content": "\n".join(text_parts)})

        # Block if no credits
        for w in research.get("warnings", []):
            if "exhausted" in w.lower():
                self._pipeline = None
                self._pipeline_phase = None
                return {"text": "\n".join(text_parts), "mode": "control"}

        # ── Phase 2: PLAN ──
        plan = await pipeline.run_phase_2_plan()
        self._pipeline_plan = plan

        tools = plan.get('tools', [])
        reasoning = plan.get('tools_reasoning', {})
        text_parts.append(f"\n📋 **Build Plan: {plan.get('name', 'Agent')}** {plan.get('icon', '🤖')}")
        text_parts.append(f"> {plan.get('goal', '')}\n")
        text_parts.append("**Tools:**")
        for t in tools:
            reason = reasoning.get(t, "")
            text_parts.append(f"  - `{t}` — {reason}" if reason else f"  - `{t}`")
        text_parts.append(f"\n**Model:** {plan.get('model', '')} — {plan.get('model_reasoning', '')}")
        text_parts.append(f"**Temperature:** {plan.get('temperature', 0.5)} — {plan.get('temperature_reasoning', '')}")
        if plan.get('risks'):
            text_parts.append(f"\n⚠️ **Risks:** {', '.join(plan['risks'])}")
        if plan.get('recommendations'):
            text_parts.append(f"💡 **Tips:** {', '.join(plan['recommendations'])}")
        if plan.get('duplicate_warning'):
            text_parts.append(f"⚠️ {plan['duplicate_warning']}")
        await self._emit_progress("text", {"content": "\n".join(text_parts)})

        # ── Phase 3: VERIFY ──
        verification = await pipeline.run_phase_3_verify(plan)
        if not verification.get("provider_ok"):
            plan["model"] = "groq/llama-3.3-70b-versatile"
            text_parts.append("\n⚠️ Provider issue — switched to fallback model.")
        else:
            text_parts.append(f"\n✅ **Verification passed** — {plan.get('model', '')} responding, tools ready")
        for w in verification.get("warnings", []):
            text_parts.append(f"  - ⚠️ {w}")
        await self._emit_progress("text", {"content": "\n".join(text_parts)})

        # ── Phase 4: GENERATE PROMPT ──
        prompt = await pipeline.run_phase_4_generate_prompt(plan)
        text_parts.append(f"\n🧠 **Agent instructions generated** ({len(prompt)} chars)")
        await self._emit_progress("text", {"content": "\n".join(text_parts)})

        # ── Phase 5: BUILD ──
        build_result = await pipeline.run_phase_5_build(plan)
        agent_id = build_result.get("agent_id", "")
        success = build_result.get("outcome") == "SUCCESS"

        if success:
            text_parts.append(f"\n✅ **{plan.get('name', 'Agent')}** built successfully!")
            text_parts.append(f"Agent ID: `{agent_id}`")
            if build_result.get("verified"):
                text_parts.append("✅ Verified in database")
            if build_result.get("identity_hash"):
                text_parts.append(f"✅ Blockchain identity: `{build_result['identity_hash'][:16]}...`")
            await self._emit_progress("text", {"content": "\n".join(text_parts)})

            # ── Phase 6: TEST ──
            test_result = await pipeline.run_phase_6_test(agent_id, plan.get("goal", ""))
            if test_result.get("status") == "success":
                text_parts.append(
                    f"\n🧪 **Test passed** — {test_result.get('steps', 0)} steps "
                    f"in {test_result.get('duration_s', 0):.1f}s"
                )
            elif test_result.get("status") == "failed":
                text_parts.append(f"\n⚠️ Test run failed: {test_result.get('error', 'unknown')}")
            else:
                text_parts.append(f"\nℹ️ Test: {test_result.get('status', 'skipped')}")

            # ── Phase 7: OFFERS ──
            offers = await pipeline.generate_offers(
                agent_id, plan.get("name", ""),
                plan.get("goal", ""), plan.get("tools", []),
            )
            if offers:
                text_parts.append("\n---\n**What's next?**")
                for o in offers:
                    text_parts.append(f"  - **{o['title']}**: {o['description']}")

            plan["_built_agent_id"] = agent_id
            self._pipeline_phase = "waiting_post_build"

            text = "\n".join(text_parts)
            await self._emit_progress("text", {"content": text})

            option_labels = [o["title"] for o in offers[:4]] if offers else ["Run it now"]
            await self._emit_progress("options", {
                "question": "What's next?",
                "options": option_labels,
            })

            return {
                "text": text, "mode": "control",
                "pipeline_phase": "waiting_post_build",
                "agent_id": agent_id,
                "build_result": build_result,
                "test_result": test_result,
                "offers": offers,
                "options": {"question": "What's next?", "options": option_labels},
            }
        else:
            error = build_result.get("error", "Unknown build error")
            text_parts.append(f"\n❌ Build failed: {error}")
            self._pipeline = None
            self._pipeline_phase = None
            self._pipeline_plan = None
            text = "\n".join(text_parts)
            await self._emit_progress("text", {"content": text})
            return {"text": text, "mode": "control", "error": error}

    async def _continue_build_pipeline(self, user_message: str) -> Dict[str, Any]:
        """Handle post-build follow-up actions (schedule, run, etc.)."""
        pipeline = self._pipeline
        plan = self._pipeline_plan
        msg_lower = user_message.lower().strip()

        if not pipeline or not plan:
            self._pipeline = None
            self._pipeline_phase = None
            self._pipeline_plan = None
            return await self._run_loop(classify_mode(user_message, True))

        agent_id = plan.get("_built_agent_id", "")

        # Run / test the agent
        if agent_id and any(kw in msg_lower for kw in ("run", "test", "execute", "now", "try")):
            result = await pipeline.run_phase_6_test(agent_id, plan.get("goal", ""))
            self._pipeline = None
            self._pipeline_phase = None
            self._pipeline_plan = None
            status = result.get("status", "unknown")
            if status == "success":
                text = (f"✅ Agent ran successfully — {result.get('steps', 0)} steps "
                        f"in {result.get('duration_s', 0):.1f}s")
            elif status == "failed":
                text = f"❌ Run failed: {result.get('error', 'unknown')}"
            else:
                text = f"ℹ️ Run status: {status}"
            await self._emit_progress("text", {"content": text})
            return {"text": text, "mode": "control", "test_run": result}

        # Schedule — hand off to normal orchestrator which has set_trigger tool
        self._pipeline = None
        self._pipeline_phase = None
        self._pipeline_plan = None
        return await self._run_loop(classify_mode(user_message, True))

    # ── Core LLM loop (for non-build intents) ──

    async def _run_loop(self, mode: OperationMode) -> Dict[str, Any]:
        # Always refresh workspace context before each loop — prevents stale state
        try:
            await self.initialize_session()
        except Exception as e:
            logger.warning(f"[Orch] context refresh failed: {e}")

        context_block = self._build_context_block()
        agents = self.context.get("workspace", {}).get("agents", [])
        agent_count = len(agents)
        agent_names = [a.get("name", "?") for a in agents]

        # Smart prompt selection: neural classifier picks relevant prompt modules
        user_msg = self.history[-1]["content"] if self.history else ""
        router = get_router()
        await router.ensure_ready()
        system_content = router.route(
            mode=mode.value,
            user_message=user_msg,
            context_block=context_block,
            agent_count=agent_count,
            agent_names=agent_names,
            is_run_event=False,
        )

        # ── Neural tool selection: only inject relevant tools per message ──
        selected_tool_names = None
        predicted_group = "all"
        try:
            ready = await architect_tool_classifier.ensure_ready()
            if ready:
                selected_tool_names, predicted_group = \
                    architect_tool_classifier.get_tools_for_message(user_msg)
                logger.info(
                    f"[Orch] Tool classifier: group={predicted_group} "
                    f"tools={len(selected_tool_names or [])} msg={user_msg[:60]!r}"
                )
            else:
                selected_tool_names, predicted_group = fallback_get_tools(user_msg)
                logger.info(f"[Orch] Tool classifier fallback: group={predicted_group}")
        except Exception as e:
            logger.warning(f"[Orch] Tool classifier failed, using all tools: {e}")

        # Filter ORCHESTRATOR_TOOLS to only the selected subset
        if selected_tool_names and predicted_group != "none":
            name_set = set(selected_tool_names)
            selected_tools = [t for t in ORCHESTRATOR_TOOLS
                              if t["function"]["name"] in name_set]
            # Safety: if filter produced too few, fall back to all
            if len(selected_tools) < 2:
                selected_tools = ORCHESTRATOR_TOOLS
                logger.warning("[Orch] Tool filter too aggressive, using all tools")
        elif predicted_group == "none":
            selected_tools = []  # Pure text response, no tools
        else:
            selected_tools = ORCHESTRATOR_TOOLS  # Fallback: all tools

        messages = [{"role": "system", "content": system_content}]
        # For REVIEW mode, trim old history aggressively — user is asking a new question
        if mode == OperationMode.REVIEW and len(self.history) > 4:
            messages.extend(self.history[-4:])
        else:
            messages.extend(self.history)
        final_text = ""
        actions_taken = []
        _last_tool_name = ""
        _repeat_count = 0
        _MAX_REPEAT = 2  # Break if same tool called 3+ times in a row

        for iteration in range(MAX_TOOL_LOOPS):
            await self._emit_progress("thinking", {
                "iteration": iteration,
                "message": "Analyzing your request..." if iteration == 0 else "Processing next step..."
            })

            try:
                resp = await call_llm(
                    messages=messages,
                    tools=selected_tools,
                    model="groq/llama-3.3-70b-versatile",
                    temperature=0.5,
                    max_tokens=MAX_TOKENS,
                    user_api_keys=self._user_api_keys,
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
                print(f"[Orch] NO TOOL CALLS - LLM text response: {content[:200]}", flush=True)
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

                print(f"[Orch] TOOL CALL: {name}({args})", flush=True)
                logger.warning(f"[Orch] tool: {name}({list(args.keys())})")

                # Repeated tool detection — break infinite loops
                if name == _last_tool_name:
                    _repeat_count += 1
                else:
                    _last_tool_name = name
                    _repeat_count = 0

                if _repeat_count >= _MAX_REPEAT:
                    logger.warning(f"[Orch] BREAKING: {name} called {_repeat_count + 1}x in a row — forcing text response")
                    # Inject nudge so LLM produces a text answer
                    messages.append({
                        "role": "tool", "tool_call_id": tc_id,
                        "content": json.dumps({"notice": f"You already called {name} {_repeat_count + 1} times. You have the data. Now respond to the user with a text answer — do NOT call any more tools."}, default=str),
                    })
                    await self._emit_progress("warning", {"message": f"Breaking repeated {name} loop"})
                    break  # break inner for-loop to re-enter LLM call without tools

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
                    print(f"[Orch] RESULT: {str(result)[:300]}", flush=True)
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
                            user_api_keys=self._user_api_keys,
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
                            user_api_keys=self._user_api_keys,
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
                    # Extract the question/text from the options so it appears in chat
                    if not final_text.strip():
                        opt_question = ""
                        if isinstance(result, dict):
                            opt_question = result.get("question", "")
                        if opt_question:
                            final_text = opt_question
                        else:
                            final_text = _summarize_actions(actions_taken)
                    # Emit as text event so SSE streaming path captures it
                    await self._emit_progress("text", {"content": final_text})
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
    if name == "delegate_to_agent":
        return f"Delegating task to agent {args.get('agent_id', '')[:8]}..."
    if name == "delegate_by_name":
        return f"Delegating task to agent '{args.get('agent_name', '?')}'..."
    if name == "create_task":
        return f"Creating task: {args.get('title', '?')}..."
    if name == "list_tasks":
        return "Loading tasks..."
    if name == "update_task":
        return f"Updating task {args.get('task_id', '')}..."
    if name == "brainstorm":
        return "Storing brainstorm idea..."
    if name == "get_workspace_plan":
        return "Loading workspace plan..."
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
    if name in ("delegate_to_agent", "delegate_by_name"):
        return f"Delegated to '{result.get('delegated_to', '?')}' — {result.get('outcome', '?')}: {result.get('summary', '')[:100]}"
    if name == "create_task":
        return f"Task created: {result.get('task', {}).get('title', '')}"
    if name == "brainstorm":
        return f"Brainstorm stored"
    if name == "get_workspace_plan":
        return f"Workspace plan loaded"
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
        elif tool == "delete_all_agents":
            if err:
                parts.append(f"Tried to delete all agents but hit an error: {err}")
            else:
                count = r.get("deleted_count", 0)
                err_count = r.get("error_count", 0)
                if err_count:
                    parts.append(f"Deleted {count} agents, {err_count} failed.")
                else:
                    parts.append(f"Deleted all {count} agents.")
        elif tool == "stop_run":
            parts.append("Stopped the run.")
        elif tool in ("delegate_to_agent", "delegate_by_name"):
            delegated = r.get("delegated_to", "agent")
            outcome = r.get("outcome", "?")
            summary = r.get("summary", "")[:150]
            if err:
                parts.append(f"Tried to delegate to **{delegated}** but failed: {err}")
            else:
                parts.append(f"Delegated to **{delegated}** — {outcome}. {summary}")
        elif tool == "create_task":
            task = r.get("task", {})
            parts.append(f"Created task: **{task.get('title', '?')}** [{task.get('priority', 'medium')}]")
        elif tool == "update_task":
            task = r.get("task", {})
            parts.append(f"Updated task {task.get('id', '?')} → {task.get('status', '?')}")
        elif tool == "brainstorm":
            content = r.get("content", "")[:80]
            parts.append(f"Stored brainstorm: {content}")
        elif tool == "get_workspace_plan":
            parts.append("Loaded workspace plan.")
        elif tool == "list_tasks":
            parts.append("Retrieved task list.")
        elif tool == "present_options":
            pass
    return " ".join(parts) if parts else ""
