"""Build Pipeline — Multi-step interactive agent creation workflow.

Instead of one LLM call that dumps everything, this drives a structured
multi-step conversation where each phase streams via SSE and some steps
wait for user input before proceeding.

Pipeline phases:
  1. RESEARCH  — check integrations, credits, memory, similar agents
  2. PLAN      — LLM crafts a build plan (name, goal, tools, model, temp)
  3. CONFIGURE — walk user through each setting with present_options
  4. PROMPT    — generate agent system prompt, show for review
  5. VERIFY    — test provider health, check tool connections
  6. BUILD     — create agent, blockchain, memory
  7. TEST      — run agent with test goal, stream results
  8. OFFER     — schedule, alerts, marketplace, improvements
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

from src.core.config import AGENT_ENGINE_URL
from src.core.llm_client import call_llm, call_llm_stream, resolve_model, DEFAULT_MODEL, FAST_MODEL, REASONING_MODEL
from src.services.billing import billing_client
from src.services.memory.memory_store import MemoryStore
from src.builder.agent_type_classifier import get_agent_type_classifier, fallback_classify
from src.builder.specialised_prompt_writer import get_specialised_builder_prompt
from src.knowledge.agent_recipes import get_recipe_context

logger = logging.getLogger(__name__)

# Available models for user to pick from
MODELS = {
    "groq/llama-3.3-70b-versatile": {"label": "Groq Llama 70B", "speed": "fast", "cost": "low", "best_for": "90% of tasks"},
    "openai/gpt-4o": {"label": "GPT-4o", "speed": "medium", "cost": "high", "best_for": "complex reasoning"},
}


class BuildPipeline:
    """Code-driven multi-step agent build workflow with SSE streaming."""

    def __init__(
        self,
        workspace_id: str,
        user_id: str,
        user_message: str,
        emit: Callable,
        ws_db: Any,
        user_api_keys: Optional[Dict] = None,
        preferred_provider: str = "",
        preferred_model: str = "",
    ):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.user_message = user_message
        self._emit = emit
        self.ws_db = ws_db
        self._user_api_keys = user_api_keys
        self._preferred_provider = preferred_provider
        self._preferred_model = preferred_model

        # Pipeline state — populated as we go
        self.research: Dict[str, Any] = {}
        self.plan: Dict[str, Any] = {}
        self.agent_prompt: str = ""
        self.verification: Dict[str, Any] = {}

    async def run_phase_1_research(self) -> Dict[str, Any]:
        """Phase 1: RESEARCH — gather intel before planning."""
        await self._emit("phase", {"phase": "research", "message": "Researching your request..."})

        result: Dict[str, Any] = {
            "credits": {}, "integrations": {}, "memory_context": "",
            "existing_agents": [], "warnings": [],
        }

        async def _check_credits():
            try:
                info = await billing_client.check_credits(self.user_id)
                result["credits"] = info
                if not info.get("has_credits", True):
                    result["warnings"].append("Credits exhausted — cannot build agent.")
                elif info.get("remaining", 9999) < 100:
                    result["warnings"].append(
                        f"Low credits ({info.get('remaining', '?')} remaining)."
                    )
            except Exception as e:
                logger.warning(f"[Pipeline] Credit check failed: {e}")

        async def _check_integrations():
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.get(
                        f"{AGENT_ENGINE_URL}/agents/integrations",
                        headers=self.ws_db._headers,
                    )
                    if resp.status_code == 200:
                        result["integrations"] = resp.json()
            except Exception as e:
                logger.warning(f"[Pipeline] Integration check failed: {e}")

        async def _check_memory():
            try:
                mem = MemoryStore(self.workspace_id, "architect")
                context = await mem.ask_memory(
                    f"Past experience building agents for: {self.user_message[:200]}"
                )
                if context and not context.get("error"):
                    answer = context.get("answer", "") or context.get("response", "")
                    if answer:
                        result["memory_context"] = str(answer)[:500]
            except Exception:
                pass

        async def _check_existing():
            try:
                snapshot = await self.ws_db.get_snapshot()
                result["existing_agents"] = snapshot.get("agents", [])
            except Exception:
                pass

        await asyncio.gather(
            _check_credits(), _check_integrations(),
            _check_memory(), _check_existing(),
            return_exceptions=True,
        )

        self.research = result

        # Emit research findings
        connected = result.get("integrations", {})
        connected_list = connected.get("connected", []) if isinstance(connected, dict) else []
        credits_info = result.get("credits", {})

        await self._emit("research_complete", {
            "credits_remaining": credits_info.get("remaining", "unknown"),
            "integrations_connected": connected_list,
            "existing_agent_count": len(result.get("existing_agents", [])),
            "has_memory_context": bool(result.get("memory_context")),
            "warnings": result.get("warnings", []),
        })

        return result

    async def run_phase_2_plan(self) -> Dict[str, Any]:
        """Phase 2: PLAN — LLM generates a build plan, presented to user."""
        await self._emit("phase", {"phase": "plan", "message": "Creating build plan..."})

        connected = self.research.get("integrations", {})
        connected_list = connected.get("connected", []) if isinstance(connected, dict) else []
        existing = self.research.get("existing_agents", [])
        existing_names = [a.get("name", "") for a in existing]

        recipe_context = get_recipe_context(self.user_message)

        plan_prompt = f"""You are an elite agent engineer planning an agent build. Use your expert knowledge to create the OPTIMAL configuration.

User request: "{self.user_message}"

{recipe_context}

Context:
- Connected integrations: {', '.join(connected_list) if connected_list else 'none'}
- Existing agents: {', '.join(existing_names) if existing_names else 'none'}
- Memory context: {self.research.get('memory_context', 'none')[:300]}

Use the expert recommendation above as your baseline. Adjust tools/model/temperature ONLY if the specific request warrants deviation.
Respond with ONLY a JSON object (no markdown, no explanation):
{{
  "name": "Agent Name",
  "icon": "single emoji",
  "goal": "Clear, specific goal (2-3 sentences, NO recurrence language)",
  "tools": ["tool1", "tool2"],
  "tools_reasoning": {{"tool1": "why needed", "tool2": "why needed"}},
  "model": "groq/llama-3.3-70b-versatile",
  "model_reasoning": "why this model",
  "temperature": 0.5,
  "temperature_reasoning": "why this temperature",
  "max_loops": 30,
  "max_loops_reasoning": "why this many loops",
  "risks": ["any scope or cost risks"],
  "recommendations": ["any improvements or additions worth considering"]
}}"""

        try:
            _plan_tokens = ""
            async def _on_plan_token(token: str):
                nonlocal _plan_tokens
                _plan_tokens += token
                await self._emit("stream_token", {"phase": "plan", "content": _plan_tokens})

            resp = await call_llm_stream(
                messages=[{"role": "user", "content": plan_prompt}],
                model=resolve_model(self._preferred_provider, self._preferred_model, FAST_MODEL), max_tokens=2000, temperature=0.3,
                user_api_keys=self._user_api_keys,
                on_chunk=_on_plan_token,
            )
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")

            # Parse JSON from response
            import json
            # Strip markdown code fences if present
            clean = content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()

            plan = json.loads(clean)
        except Exception as e:
            logger.error(f"[Pipeline] Plan generation failed: {e}")
            # Fallback plan
            plan = {
                "name": "New Agent",
                "icon": "🤖",
                "goal": self.user_message,
                "tools": ["web_search", "fetch_url"],
                "tools_reasoning": {"web_search": "general search", "fetch_url": "read pages"},
                "model": DEFAULT_MODEL,
                "model_reasoning": "default fast model",
                "temperature": 0.5,
                "temperature_reasoning": "balanced",
                "max_loops": 30,
                "max_loops_reasoning": "standard",
                "risks": [],
                "recommendations": [],
            }

        # Check for duplicate
        for existing_agent in self.research.get("existing_agents", []):
            if existing_agent.get("name", "").lower().strip() == plan.get("name", "").lower().strip():
                plan["duplicate_warning"] = f"Agent '{plan['name']}' already exists. Will update it instead of creating a duplicate."
                plan["existing_agent_id"] = existing_agent.get("id", "")
                break

        self.plan = plan

        await self._emit("plan_ready", {
            "plan": plan,
            "message": "Here's my build plan — review each setting:",
        })

        return plan

    async def run_phase_3_verify(self, final_plan: Dict) -> Dict[str, Any]:
        """Phase 3: VERIFY — test provider, check tool connections."""
        await self._emit("phase", {"phase": "verify", "message": "Verifying everything works..."})

        model = final_plan.get("model", DEFAULT_MODEL)
        tools = final_plan.get("tools", [])
        verification: Dict[str, Any] = {"provider_ok": True, "tools_checked": [], "warnings": []}

        # Test LLM provider
        await self._emit("verify_step", {"step": "provider", "message": f"Testing {model}..."})
        try:
            test_resp = await call_llm(
                messages=[{"role": "user", "content": "Reply with OK"}],
                model=model, max_tokens=5, temperature=0,
                user_api_keys=self._user_api_keys,
            )
            content = (test_resp.get("choices", [{}])[0]
                       .get("message", {}).get("content", ""))
            if content:
                verification["provider_ok"] = True
                await self._emit("verify_step", {"step": "provider", "status": "ok",
                                                  "message": f"✓ {model} is responding"})
            else:
                verification["provider_ok"] = False
                verification["warnings"].append(f"{model} returned empty response")
                await self._emit("verify_step", {"step": "provider", "status": "fail",
                                                  "message": f"✗ {model} returned empty — will use fallback"})
        except Exception as e:
            verification["provider_ok"] = False
            verification["warnings"].append(f"{model} failed: {str(e)[:80]}")
            await self._emit("verify_step", {"step": "provider", "status": "fail",
                                              "message": f"✗ {model} not responding — will use fallback"})

        # Check tool connections (for OAuth tools)
        connected = self.research.get("integrations", {})
        connected_list = connected.get("connected", []) if isinstance(connected, dict) else []
        for tool in tools[:8]:
            if tool in connected_list:
                verification["tools_checked"].append({"tool": tool, "ok": True, "note": "connected"})
                await self._emit("verify_step", {"step": "tool", "tool": tool, "status": "ok",
                                                  "message": f"✓ {tool} — connected"})
            elif tool in ("web_search", "fetch_url", "scrape_page", "deep_research",
                          "news_search", "image_search", "stock_market_data"):
                verification["tools_checked"].append({"tool": tool, "ok": True, "note": "builtin"})
                await self._emit("verify_step", {"step": "tool", "tool": tool, "status": "ok",
                                                  "message": f"✓ {tool} — built-in, always available"})
            else:
                needs_oauth = tool in (
                    "google_calendar", "google_sheets", "google_drive", "google_docs",
                    "gmail", "slack", "discord", "github", "notion", "hubspot",
                    "salesforce", "airtable", "linear", "asana", "clickup",
                )
                if needs_oauth:
                    verification["tools_checked"].append({"tool": tool, "ok": False, "note": "not connected"})
                    verification["warnings"].append(f"{tool} requires OAuth connection")
                    await self._emit("verify_step", {
                        "step": "tool", "tool": tool, "status": "warning",
                        "message": f"⚠ {tool} — needs OAuth connection (go to Settings → Integrations)"
                    })
                else:
                    verification["tools_checked"].append({"tool": tool, "ok": True, "note": "available"})
                    await self._emit("verify_step", {"step": "tool", "tool": tool, "status": "ok",
                                                      "message": f"✓ {tool} — available"})

        self.verification = verification

        all_ok = verification["provider_ok"] and not verification.get("warnings")
        await self._emit("verify_complete", {
            "all_ok": all_ok,
            "provider_ok": verification["provider_ok"],
            "tool_results": verification["tools_checked"],
            "warnings": verification["warnings"],
        })

        return verification

    async def run_phase_4_generate_prompt(self, final_plan: Dict) -> str:
        """Phase 4: PROMPT — generate the agent's system prompt."""
        await self._emit("phase", {"phase": "prompt", "message": "Generating agent instructions..."})

        goal = final_plan.get("goal", self.user_message)
        tools = final_plan.get("tools", [])

        # Neural agent type classification
        classifier = get_agent_type_classifier()
        try:
            await classifier.ensure_ready()
            result = classifier.classify(goal, tools)
            agent_type = result["type"]
            confidence = result["confidence"]
        except Exception:
            agent_type = fallback_classify(goal)
            confidence = 0.0

        await self._emit("prompt_step", {
            "message": f"Agent type: {agent_type} (confidence: {confidence:.0%})",
            "agent_type": agent_type,
        })

        builder_system = get_specialised_builder_prompt(agent_type)
        tool_list = ", ".join(tools) if tools else "web_search, fetch_url"

        now = datetime.now(timezone.utc)
        date_context = f"Current date: {now.strftime('%Y-%m-%d')} (year {now.year}). Agent must always search for current/recent data."

        _prompt_tokens = ""
        async def _on_prompt_token(token: str):
            nonlocal _prompt_tokens
            _prompt_tokens += token
            if len(_prompt_tokens) % 50 < len(token):
                await self._emit("stream_token", {"phase": "prompt", "content": _prompt_tokens})

        resp = await call_llm_stream(messages=[
            {"role": "system", "content": builder_system},
            {"role": "user", "content": f"Goal: {goal}\nAvailable tools: {tool_list}\n\n{date_context}"}
        ], model=resolve_model(self._preferred_provider, self._preferred_model, REASONING_MODEL), max_tokens=8192, temperature=0.4,
            user_api_keys=self._user_api_keys,
            on_chunk=_on_prompt_token)
        prompt = resp.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not prompt:
            prompt = (f"ROLE: Autonomous {agent_type} agent\nGOAL: {goal}\nSTEPS:\n"
                      f"1. Use {tool_list} to gather data\n"
                      f"2. Process and analyze results\n"
                      f"3. Store output in agent database\n"
                      f"OUTPUT FORMAT: Structured summary with source URLs")

        self.agent_prompt = prompt

        await self._emit("prompt_ready", {
            "prompt_preview": prompt[:500],
            "prompt_length": len(prompt),
            "agent_type": agent_type,
            "message": "Agent instructions generated — review below:",
        })

        return prompt

    async def run_phase_5_build(self, final_plan: Dict) -> Dict[str, Any]:
        """Phase 5: BUILD — actually create the agent."""
        await self._emit("phase", {"phase": "build", "message": f"Building '{final_plan.get('name')}'..."})

        from src.builder.builder import Builder

        async def _fwd_progress(data):
            await self._emit("build_progress", data)

        builder = Builder(
            self.workspace_id, self.user_id,
            on_progress=_fwd_progress,
            user_api_keys=self._user_api_keys,
            preferred_provider=self._preferred_provider,
            preferred_model=self._preferred_model,
        )

        # If duplicate, modify instead
        if final_plan.get("existing_agent_id"):
            await self._emit("build_step", {"message": "Updating existing agent..."})
            result = await builder.modify_agent(
                final_plan["existing_agent_id"],
                add_tools=final_plan.get("tools"),
                goal=final_plan.get("goal"),
                model=final_plan.get("model"),
                temperature=final_plan.get("temperature"),
                max_loops=final_plan.get("max_loops"),
            )
        else:
            result = await builder.build(
                name=final_plan.get("name", "New Agent"),
                goal=final_plan.get("goal", self.user_message),
                icon=final_plan.get("icon", "🤖"),
                tools=final_plan.get("tools", []),
                max_loops=final_plan.get("max_loops", 30),
                temperature=final_plan.get("temperature", 0.5),
                model=final_plan.get("model", DEFAULT_MODEL),
                skip_test=True,
            )

        success = result.get("outcome") == "SUCCESS"
        await self._emit("build_complete", {
            "success": success,
            "agent_id": result.get("agent_id", ""),
            "name": final_plan.get("name", ""),
            "result": {k: v for k, v in result.items()
                       if k in ("agent_id", "outcome", "name", "verified",
                                "tools_all_ok", "test_run", "identity_hash")},
        })

        return result

    async def run_phase_6_test(self, agent_id: str, goal: str) -> Dict[str, Any]:
        """Phase 6: TEST — run the agent, stream live steps, return final output."""
        await self._emit("phase", {"phase": "test", "message": "Running test execution..."})

        test_goal = f"Quick test: {goal[:100]}. Perform ONE step only and report what you found."

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{AGENT_ENGINE_URL}/agents/{agent_id}/sessions",
                    headers=self.ws_db._headers,
                    json={"goal": test_goal, "max_steps": 5, "test_mode": True, "mode": "autonomous"},
                )
                if resp.status_code not in (200, 201):
                    await self._emit("test_result", {
                        "status": "skip",
                        "message": f"Could not start test session (status {resp.status_code})",
                    })
                    return {"status": "skip"}

                session = resp.json()
                session_id = session.get("session_id") or session.get("id", "")

            if not session_id:
                return {"status": "skip", "note": "No session_id returned"}

            await self._emit("test_step", {
                "message": f"Test session started ({session_id[:8]}...)",
                "session_id": session_id,
            })

            # Poll for completion and stream live steps
            t0 = time.time()
            last_step_count = 0
            for i in range(24):  # 24 × 5s = 120s max
                await asyncio.sleep(5)
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        poll = await client.get(
                            f"{AGENT_ENGINE_URL}/agents/sessions/{session_id}",
                            headers=self.ws_db._headers,
                        )
                        if poll.status_code != 200:
                            continue
                        data = poll.json()
                        status = data.get("status", "")
                        elapsed = time.time() - t0

                        # Fetch and emit new steps as they appear
                        steps = data.get("steps", [])
                        if isinstance(steps, list) and len(steps) > last_step_count:
                            for step in steps[last_step_count:]:
                                step_type = step.get("action_type", step.get("type", "step"))
                                reasoning = step.get("reasoning", "")
                                tool_name = step.get("tool_name", "")
                                output_preview = str(step.get("output", step.get("output_data", "")))[:300]
                                await self._emit("test_step", {
                                    "message": f"🔧 {tool_name}: {reasoning[:150]}" if tool_name else f"💭 {reasoning[:150]}",
                                    "tool": tool_name,
                                    "reasoning": reasoning[:300],
                                    "output_preview": output_preview,
                                    "status": status,
                                })
                            last_step_count = len(steps)
                        elif status == "running":
                            await self._emit("test_step", {
                                "message": f"Running... ({elapsed:.0f}s)",
                                "status": status,
                                "elapsed_s": elapsed,
                            })

                        if status in ("completed", "success", "done"):
                            final_output = data.get("final_output", "") or data.get("output", "")
                            result = {
                                "status": "success",
                                "session_id": session_id,
                                "steps": data.get("steps_executed", len(steps)),
                                "duration_s": elapsed,
                                "final_output": str(final_output)[:2000],
                            }
                            await self._emit("test_result", {
                                "status": "success",
                                "message": f"✓ Test passed — {result['steps']} steps in {elapsed:.1f}s",
                                **result,
                            })
                            return result
                        elif status in ("failed", "error", "cancelled"):
                            result = {
                                "status": "failed",
                                "session_id": session_id,
                                "error": data.get("error", data.get("error_message", "unknown")),
                            }
                            await self._emit("test_result", {
                                "status": "failed",
                                "message": f"✗ Test failed: {result['error']}",
                                **result,
                            })
                            return result
                        elif status in ("waiting_approval",):
                            await self._emit("test_step", {
                                "message": "⚠️ Approval required — auto-approving for test...",
                                "status": status,
                            })
                            # Try to auto-approve for test runs
                            try:
                                async with httpx.AsyncClient(timeout=10.0) as ac:
                                    await ac.post(
                                        f"{AGENT_ENGINE_URL}/agents/sessions/{session_id}/approve",
                                        headers=self.ws_db._headers,
                                        json={"approved": True},
                                    )
                            except Exception:
                                pass
                except Exception:
                    pass

            await self._emit("test_result", {
                "status": "timeout",
                "message": "Test run timed out after 120s (agent may still be running)",
            })
            return {"status": "timeout", "session_id": session_id}

        except Exception as e:
            await self._emit("test_result", {
                "status": "error", "message": f"Test error: {str(e)[:200]}",
            })
            return {"status": "error", "note": str(e)[:200]}

    async def run_self_heal(self, agent_id: str, plan: Dict, error: str) -> Optional[str]:
        """Diagnose a test failure and attempt to fix the agent automatically."""
        await self._emit("phase", {"phase": "self_heal", "message": f"Diagnosing failure: {error[:100]}..."})

        diagnosis_prompt = f"""An agent test run FAILED. Diagnose the root cause and suggest a fix.

Agent: {plan.get('name', 'unknown')}
Goal: {plan.get('goal', 'unknown')}
Tools: {plan.get('tools', [])}
Model: {plan.get('model', 'unknown')}
Error: {error}

Respond with ONLY a JSON object:
{{
  "cause": "brief root cause",
  "fix_type": "one of: swap_tool, add_tool, update_prompt, adjust_config, unfixable",
  "fix_detail": "specific fix to apply",
  "swap_from": "tool to remove (if swap_tool)",
  "swap_to": "tool to add (if swap_tool or add_tool)",
  "new_max_loops": null or integer (if adjust_config)
}}"""

        try:
            resp = await call_llm(
                messages=[{"role": "user", "content": diagnosis_prompt}],
                model=resolve_model(self._preferred_provider, self._preferred_model, FAST_MODEL), max_tokens=500, temperature=0.2,
                user_api_keys=self._user_api_keys,
            )
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            import json
            clean = content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()
            diagnosis = json.loads(clean)
        except Exception as e:
            logger.warning(f"[Pipeline] Self-heal diagnosis failed: {e}")
            return None

        fix_type = diagnosis.get("fix_type", "unfixable")
        if fix_type == "unfixable":
            return None

        # Apply the fix via Agent Engine
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                if fix_type in ("swap_tool", "add_tool"):
                    current_tools = list(plan.get("tools", []))
                    if fix_type == "swap_tool" and diagnosis.get("swap_from"):
                        if diagnosis["swap_from"] in current_tools:
                            current_tools.remove(diagnosis["swap_from"])
                    if diagnosis.get("swap_to"):
                        current_tools.append(diagnosis["swap_to"])
                    plan["tools"] = current_tools
                    resp = await client.patch(
                        f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                        headers=self.ws_db._headers,
                        json={"tools": current_tools},
                    )
                    return f"Updated tools: {current_tools}"

                elif fix_type == "adjust_config":
                    updates = {}
                    if diagnosis.get("new_max_loops"):
                        updates["max_loops"] = diagnosis["new_max_loops"]
                        plan["max_loops"] = diagnosis["new_max_loops"]
                    if updates:
                        resp = await client.patch(
                            f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                            headers=self.ws_db._headers,
                            json=updates,
                        )
                        return f"Updated config: {updates}"

                elif fix_type == "update_prompt":
                    # Append fix guidance to existing prompt
                    fix_detail = diagnosis.get("fix_detail", "")
                    if fix_detail:
                        resp = await client.patch(
                            f"{AGENT_ENGINE_URL}/agents/{agent_id}",
                            headers=self.ws_db._headers,
                            json={"system_prompt_append": f"\n\nIMPORTANT FIX: {fix_detail}"},
                        )
                        return f"Updated prompt: {fix_detail[:100]}"

        except Exception as e:
            logger.warning(f"[Pipeline] Self-heal fix failed: {e}")
            return None

        return diagnosis.get("fix_detail", "Applied fix")

    async def generate_offers(self, agent_id: str, name: str, goal: str, tools: List[str]) -> List[Dict]:
        """Phase 7: OFFER — generate post-build suggestions."""
        await self._emit("phase", {"phase": "offers", "message": "Generating suggestions..."})

        offers = []
        goal_lower = goal.lower()

        if any(kw in goal_lower for kw in [
            "monitor", "daily", "check", "track", "watch", "alert",
            "report", "scrape", "collect", "digest", "summarize",
            "news", "price", "stock", "weather", "feed",
        ]):
            offers.append({
                "type": "schedule", "title": "Set up automatic scheduling",
                "description": f"'{name}' looks like a recurring task. Schedule it to run daily, hourly, or custom?",
                "action": "create_schedule", "agent_id": agent_id,
            })

        if any(kw in goal_lower for kw in ["alert", "notify", "warn", "detect", "monitor"]):
            offers.append({
                "type": "alert", "title": "Configure alerts",
                "description": "Set up anomaly detection triggers for notifications.",
                "action": "create_anomaly_trigger", "agent_id": agent_id,
            })

        offers.append({
            "type": "run_now", "title": "Run it now",
            "description": f"Execute '{name}' with its full goal right now.",
            "action": "run_agent", "agent_id": agent_id,
        })

        offers.append({
            "type": "marketplace", "title": "Publish to marketplace",
            "description": f"Share '{name}' with the community.",
            "action": "publish_agent", "agent_id": agent_id,
        })

        await self._emit("offers_ready", {"offers": offers})
        return offers
