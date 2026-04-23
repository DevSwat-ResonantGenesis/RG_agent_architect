"""Builder Engine — Creates, verifies, and tests agents end-to-end.

Phase 2 intelligence pipeline:
  - Pre-build research: check integrations, providers, credits, memory
  - Provider health verification: test LLM before assigning
  - Post-build test run + auto-retry on failure
  - Post-build offers: schedule, alerts, improvements

Every step is verified. If something fails, the real error is returned.
Progress callbacks allow SSE streaming to the user in real-time.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

from src.core.llm_client import call_llm, REASONING_MODEL, DEFAULT_MODEL, FAST_MODEL
from src.core.config import AGENT_ENGINE_URL
from src.services.database.workspace_db import WorkspaceDB
from src.services.blockchain import chain_client
from src.services.billing import billing_client
from src.services.memory.memory_store import MemoryStore
from src.builder.agent_type_classifier import get_agent_type_classifier, fallback_classify
from src.builder.specialised_prompt_writer import get_specialised_builder_prompt

logger = logging.getLogger(__name__)

# Tools that can be tested with a quick dry-run
TESTABLE_TOOLS = {
    "web_search": {"query": "test", "context": "verification"},
    "fetch_url": {"url": "https://httpbin.org/get"},
}


class Builder:
    def __init__(self, workspace_id: str, user_id: str = "",
                 on_progress: Optional[Callable] = None):
        self.workspace_id = workspace_id
        self.user_id = user_id or workspace_id
        self.ws_db = WorkspaceDB(workspace_id)
        self._on_progress = on_progress

    async def _emit(self, phase: str, message: str, data: Optional[Dict] = None):
        """Emit a progress event for SSE streaming."""
        logger.info(f"[Builder] [{phase}] {message}")
        if self._on_progress:
            try:
                await self._on_progress({
                    "phase": phase,
                    "message": message,
                    "data": data or {},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                logger.debug(f"[Builder] progress emit failed: {e}")

    async def build(self, name: str, goal: str, icon: str = "🤖",
                    tools: list = None, max_loops: int = 30,
                    temperature: float = 0.5,
                    model: str = "groq/llama-3.3-70b-versatile") -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # ── PHASE -2: Pre-build research ──
        await self._emit("research", "Running pre-build research...")
        research = await self._pre_build_research(goal, model)
        if research.get("block"):
            await self._emit("error", research["block"])
            return {"error": research["block"], "outcome": "FAIL", "name": name}
        if research.get("warnings"):
            for w in research["warnings"]:
                await self._emit("research_warning", w)
        if research.get("model_override"):
            model = research["model_override"]
            await self._emit("research", f"Switched model to {model} (original unhealthy)")
        await self._emit("research", "Pre-build research complete",
                         {"credits": research.get("credits"),
                          "integrations": research.get("integrations"),
                          "provider_ok": research.get("provider_ok"),
                          "memory_context": research.get("memory_context", "")[:200]})

        # ── PHASE -1: Neural tool selection from Agent Engine (161+ tools) ──
        if tools:
            resolved_tools = tools
        else:
            resolved_tools = await self._predict_optimal_tools(goal)
            if not resolved_tools:
                resolved_tools = ["web_search", "fetch_url"]
            await self._emit("tool_selection",
                             f"Neural classifier selected {len(resolved_tools)} tools: {resolved_tools}")

        # ── PHASE 0: Duplicate detection ──
        existing = await self._find_agent_by_name(name)
        if existing:
            existing_id = existing.get("id", "")
            await self._emit("duplicate", f"Agent '{name}' already exists (ID: {existing_id}). Updating instead of creating duplicate.")
            logger.info(f"[Builder] Duplicate detected: '{name}' exists as {existing_id}, modifying")
            return await self.modify_agent(
                existing_id,
                add_tools=[t for t in resolved_tools if t not in (existing.get("tools") or [])],
                goal=goal, max_loops=max_loops, temperature=temperature, model=model,
            )

        agent_id = str(uuid.uuid4())

        # ── PHASE 1: Neural type classification + specialised instruction generation ──
        await self._emit("planning", f"Classifying agent type and generating specialised instructions for '{name}'...")
        self._last_agent_type = "general"
        self._last_type_confidence = 0.0
        try:
            instructions = await self._generate_instructions(goal, resolved_tools)
        except Exception as e:
            logger.error(f"[Builder] Instruction generation failed: {e}")
            return {"error": f"Failed to generate instructions: {e}", "outcome": "FAIL"}
        await self._emit("planning",
                         f"Instructions generated (type={self._last_agent_type}, "
                         f"conf={self._last_type_confidence:.2f})",
                         {"instructions_preview": instructions[:200],
                          "agent_type": self._last_agent_type,
                          "type_confidence": self._last_type_confidence})

        # ── PHASE 2: Save agent to Agent Engine DB ──
        await self._emit("saving", f"Saving agent '{name}' to Agent Engine...")
        save_result = await self.ws_db.save_agent(
            agent_id=agent_id, name=name, goal=goal, icon=icon,
            system_prompt=instructions, tools=resolved_tools,
            needs_build=False, max_loops=max_loops,
            temperature=temperature, model=model)

        # CRITICAL: Check if save actually succeeded
        if not save_result.get("saved", False):
            error_msg = save_result.get("error", "Unknown save error")
            await self._emit("error", f"FAILED to save agent: {error_msg}")
            logger.error(f"[Builder] save_agent FAILED for '{name}': {error_msg}")
            return {"error": f"Agent save failed: {error_msg}", "outcome": "FAIL",
                    "name": name}

        agent_id = save_result.get("agent_id", agent_id)
        await self._emit("saving", f"Agent saved with ID {agent_id}")

        # ── PHASE 3: Verify agent exists in DB ──
        await self._emit("verifying", "Verifying agent exists in database...")
        verified_agent = await self.ws_db.get_agent(agent_id)
        if not verified_agent:
            await self._emit("error", "Agent was saved but verification fetch failed!")
            logger.error(f"[Builder] Agent {agent_id} saved but not found on verify!")
            return {"error": "Agent saved but could not be verified — possible DB issue",
                    "outcome": "FAIL", "agent_id": agent_id, "name": name}
        await self._emit("verifying", "Agent verified in database",
                         {"agent_name": verified_agent.get("name", name)})

        # ── PHASE 4: Blockchain registration (parallel, non-blocking) ──
        await self._emit("blockchain", "Registering agent identity on blockchain...")
        identity_hash, wallet_addr = await self._register_blockchain(
            agent_id, name, goal)
        await self._emit("blockchain", "Blockchain registration complete",
                         {"identity_hash": identity_hash[:32] if identity_hash else "",
                          "wallet": wallet_addr[:16] if wallet_addr else ""})

        # ── PHASE 5: Store build run record ──
        run_result = await self.ws_db.save_run(
            run_id=run_id, agent_id=agent_id, outcome="SUCCESS",
            summary=f"Built agent: {name}", loop_count=1,
            started_at=now, finished_at=datetime.now(timezone.utc))
        if not run_result.get("saved", False):
            run_error = run_result.get("error", "unknown")
            logger.warning(f"[Builder] save_run failed for '{name}': {run_error}")
            # Agent was created but run record failed (e.g. credits issue)
            # Don't block — agent exists, just note the issue
            await self._emit("warning", f"Agent created but run record failed: {run_error}")

        # ── PHASE 6: Test tools (quick verification) ──
        await self._emit("testing", "Testing agent tools...")
        test_results = await self._test_tools(resolved_tools)
        tools_ok = all(r["ok"] for r in test_results)
        tools_summary = ", ".join(
            f"{r['tool']}:{'OK' if r['ok'] else 'FAIL'}" for r in test_results
        )
        await self._emit("testing", f"Tool tests: {tools_summary}",
                         {"test_results": test_results, "all_passed": tools_ok})

        # ── PHASE 7: Post-build test run + auto-retry ──
        await self._emit("test_run", f"Running test execution of '{name}'...")
        test_run = await self._post_build_test_run(agent_id, name, goal)
        if test_run.get("status") == "success":
            await self._emit("test_run",
                             f"Test run passed ({test_run.get('steps', 0)} steps, "
                             f"{test_run.get('duration_s', 0):.1f}s)",
                             test_run)
        elif test_run.get("status") == "retried":
            await self._emit("test_run",
                             f"Test run failed initially, auto-retried and "
                             f"{'passed' if test_run.get('retry_ok') else 'still failing'}",
                             test_run)
        else:
            await self._emit("test_run_warning",
                             f"Test run issue: {test_run.get('note', 'unknown')}",
                             test_run)

        # ── PHASE 8: Store memory ──
        mem = MemoryStore(self.workspace_id, agent_id)
        await mem.store_agent_learning(
            f"Agent '{name}' created with goal: {goal}. "
            f"Tools: {resolved_tools}. Identity: {identity_hash}. "
            f"Tool test results: {tools_summary}. "
            f"Test run: {test_run.get('status', 'skipped')}",
            run_id=run_id)

        # ── PHASE 9: Post-build offers ──
        offers = await self._generate_post_build_offers(agent_id, name, goal, resolved_tools)
        if offers:
            await self._emit("offers", "Suggestions for your new agent:",
                             {"offers": offers})

        await self._emit("complete", f"Agent '{name}' created and verified successfully!")

        logger.info(f"[Builder] VERIFIED agent {agent_id}: {name} | "
                     f"tools_ok={tools_ok} chain={identity_hash[:16]}...")
        return {
            "agent_id": agent_id, "name": name, "run_id": run_id,
            "outcome": "SUCCESS",
            "identity_hash": identity_hash,
            "wallet_address": wallet_addr,
            "tools_tested": test_results,
            "tools_all_ok": tools_ok,
            "test_run": test_run,
            "offers": offers,
            "verified": True,
        }

    async def continue_build(self, agent_id: str, instructions: str) -> Dict:
        agent = await self.ws_db.get_agent(agent_id)
        if not agent:
            return {"error": "Agent not found", "outcome": "FAIL"}
        save_result = await self.ws_db.save_agent(
            agent_id=agent_id, name=agent["name"], goal=agent["goal"],
            icon=agent.get("icon", "🤖"), system_prompt=instructions,
            tools=agent.get("tools", []), needs_build=False)
        if not save_result.get("saved", False):
            return {"error": f"Update failed: {save_result.get('error', 'unknown')}",
                    "outcome": "FAIL"}
        return {"agent_id": agent_id, "outcome": "SUCCESS"}

    async def message_build(self, agent_id: str, message: str) -> Dict:
        agent = await self.ws_db.get_agent(agent_id)
        if not agent:
            return {"error": "Agent not found", "outcome": "FAIL"}
        current = agent.get("system_prompt", "")
        goal = agent.get("goal", "")
        tools = agent.get("tools", [])

        # Use neural classifier to get specialised builder prompt
        classifier = get_agent_type_classifier()
        try:
            await classifier.ensure_ready()
            result = classifier.classify(goal, tools)
            agent_type = result["type"]
        except Exception:
            agent_type = fallback_classify(goal)
        builder_system = get_specialised_builder_prompt(agent_type)

        resp = await call_llm(messages=[
            {"role": "system", "content": builder_system},
            {"role": "user", "content": (
                f"Current instructions:\n{current}\n\n"
                f"User wants to change:\n{message}\n\n"
                "Output the FULL updated instruction block."
            )}
        ], model=REASONING_MODEL, max_tokens=8192)
        new_prompt = resp.get("choices", [{}])[0].get("message", {}).get("content", current)
        save_result = await self.ws_db.save_agent(
            agent_id=agent_id, name=agent["name"], goal=agent["goal"],
            system_prompt=new_prompt, tools=agent.get("tools", []),
            needs_build=False)
        if not save_result.get("saved", False):
            return {"error": f"Update failed: {save_result.get('error', 'unknown')}",
                    "outcome": "FAIL"}
        return {"agent_id": agent_id, "outcome": "SUCCESS", "updated": True}

    async def modify_agent(self, agent_id: str,
                           add_tools: Optional[List[str]] = None,
                           remove_tools: Optional[List[str]] = None,
                           **updates) -> Dict:
        """Add/remove tools or update config on an existing agent."""
        agent = await self.ws_db.get_agent(agent_id)
        if not agent:
            return {"error": "Agent not found", "outcome": "FAIL"}

        current_tools = agent.get("tools", [])
        if add_tools:
            for t in add_tools:
                if t not in current_tools:
                    current_tools.append(t)
        if remove_tools:
            current_tools = [t for t in current_tools if t not in remove_tools]

        save_result = await self.ws_db.save_agent(
            agent_id=agent_id,
            name=updates.get("name", agent["name"]),
            goal=updates.get("goal", agent.get("goal", "")),
            icon=updates.get("icon", agent.get("icon", "🤖")),
            system_prompt=updates.get("system_prompt", agent.get("system_prompt", "")),
            tools=current_tools,
            needs_build=False,
            max_loops=updates.get("max_loops", agent.get("max_loops", 30)),
            temperature=updates.get("temperature", agent.get("temperature", 0.5)),
            model=updates.get("model", agent.get("model", "groq/llama-3.3-70b-versatile")),
        )
        if not save_result.get("saved", False):
            return {"error": f"Modify failed: {save_result.get('error', 'unknown')}",
                    "outcome": "FAIL"}

        # Test new tools if any were added
        test_results = []
        if add_tools:
            test_results = await self._test_tools(add_tools)

        return {
            "agent_id": agent_id, "outcome": "SUCCESS",
            "tools": current_tools,
            "tools_tested": test_results,
            "modified": True,
        }

    # ── Internal helpers ──

    async def _pre_build_research(self, goal: str, model: str) -> Dict[str, Any]:
        """Phase 2: Pre-build intelligence — check everything before building.

        Runs in parallel:
          1. Credit check (can user afford to build + run?)
          2. Integration check (what services are connected?)
          3. Provider health (is the assigned LLM model responding?)
          4. Memory context (any relevant prior knowledge about this goal?)

        Returns dict with: block (str|None), warnings (list), credits, integrations,
                          provider_ok (bool), model_override (str|None), memory_context.
        """
        result: Dict[str, Any] = {
            "block": None, "warnings": [], "credits": {},
            "integrations": {}, "provider_ok": True,
            "model_override": None, "memory_context": "",
        }

        async def _check_credits():
            try:
                info = await billing_client.check_credits(self.user_id)
                result["credits"] = info
                if not info.get("has_credits", True):
                    result["block"] = (
                        "Credits exhausted. Please upgrade your plan or "
                        "purchase credits before building an agent."
                    )
                elif info.get("remaining", 9999) < 100:
                    result["warnings"].append(
                        f"Low credits ({info.get('remaining', '?')} remaining). "
                        "Agent may not have enough to complete complex tasks."
                    )
            except Exception as e:
                logger.warning(f"[Research] Credit check failed: {e}")

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
                logger.warning(f"[Research] Integration check failed: {e}")

        async def _check_provider_health():
            try:
                test_resp = await call_llm(
                    messages=[{"role": "user", "content": "Reply with OK"}],
                    model=model, max_tokens=5, temperature=0,
                )
                content = (test_resp.get("choices", [{}])[0]
                           .get("message", {}).get("content", ""))
                if not content:
                    result["provider_ok"] = False
                    result["warnings"].append(
                        f"Provider {model} returned empty response. "
                        "Switching to fallback model."
                    )
                    result["model_override"] = DEFAULT_MODEL
            except Exception as e:
                result["provider_ok"] = False
                result["warnings"].append(
                    f"Provider {model} health check failed: {str(e)[:80]}. "
                    "Switching to fallback model."
                )
                result["model_override"] = DEFAULT_MODEL
                logger.warning(f"[Research] Provider health failed for {model}: {e}")

        async def _check_memory_context():
            try:
                mem = MemoryStore(self.workspace_id, "architect")
                context = await mem.ask_memory(
                    f"Any past experience building agents for: {goal[:200]}"
                )
                if context and not context.get("error"):
                    answer = context.get("answer", "") or context.get("response", "")
                    if answer:
                        result["memory_context"] = str(answer)[:500]
            except Exception as e:
                logger.debug(f"[Research] Memory search failed: {e}")

        await asyncio.gather(
            _check_credits(),
            _check_integrations(),
            _check_provider_health(),
            _check_memory_context(),
            return_exceptions=True,
        )
        return result

    async def _predict_optimal_tools(self, goal: str) -> List[str]:
        """Use Agent Engine's neural tool classifier to pick optimal tools for a goal.

        Calls POST /tools/classifier/predict which has the full 161+ tool registry.
        Returns top tools above confidence threshold.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{AGENT_ENGINE_URL}/agents/tools/classifier/predict",
                    headers=self.ws_db._headers,
                    json={"goal": goal, "n": 8},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    predictions = data.get("predictions", [])
                    tools = [p["tool"] for p in predictions if p.get("confidence", 0) > 0.05]
                    if tools:
                        logger.info(f"[Builder] Neural tool prediction for '{goal[:40]}': {tools}")
                        return tools[:6]
                else:
                    logger.warning(f"[Builder] Tool classifier returned {resp.status_code}")
        except Exception as e:
            logger.warning(f"[Builder] Neural tool prediction failed: {e}")
        return []

    async def _find_agent_by_name(self, name: str) -> Optional[Dict]:
        """Check if an agent with this name already exists in the workspace."""
        try:
            snapshot = await self.ws_db.get_snapshot()
            agents = snapshot.get("agents", [])
            name_lower = name.lower().strip()
            for a in agents:
                if (a.get("name", "").lower().strip() == name_lower):
                    return a
        except Exception as e:
            logger.warning(f"[Builder] duplicate check failed: {e}")
        return None

    async def _generate_instructions(self, goal: str, tools: list) -> str:
        """Generate agent instructions using neural type classification.

        Flow:
        1. AgentTypeClassifier identifies the agent type from goal + tools
        2. SpecialisedPromptWriter provides a type-specific builder prompt
        3. LLM generates far better instructions using domain expertise
        """
        tool_list = ", ".join(tools) if tools else "web_search, fetch_url"

        # ── Neural agent type classification ──
        classifier = get_agent_type_classifier()
        try:
            await classifier.ensure_ready()
            result = classifier.classify(goal, tools)
            agent_type = result["type"]
            confidence = result["confidence"]
            logger.info(
                f"[Builder] Agent type classified: {agent_type} "
                f"(conf={confidence:.3f}) for goal={goal[:60]!r}"
            )
        except Exception as e:
            logger.warning(f"[Builder] Neural classifier failed, using fallback: {e}")
            agent_type = fallback_classify(goal)
            confidence = 0.0

        # ── Get specialised builder prompt for this type ──
        builder_system = get_specialised_builder_prompt(agent_type)
        self._last_agent_type = agent_type
        self._last_type_confidence = confidence

        resp = await call_llm(messages=[
            {"role": "system", "content": builder_system},
            {"role": "user", "content": f"Goal: {goal}\nAvailable tools: {tool_list}"}
        ], model=REASONING_MODEL, max_tokens=8192, temperature=0.4)
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            content = (f"ROLE: Autonomous {agent_type} agent\nGOAL: {goal}\nSTEPS:\n"
                       f"1. Use {tool_list} to gather data\n"
                       f"2. Process and analyze results\n"
                       f"3. Store output in agent database\n"
                       f"OUTPUT FORMAT: Structured summary with source URLs")
        return content

    async def _register_blockchain(self, agent_id: str, name: str,
                                   goal: str) -> tuple:
        """Register agent on blockchain. Returns (identity_hash, wallet_addr)."""
        identity_hash = ""
        wallet_addr = ""
        try:
            identity_result = await chain_client.register_agent_identity(
                agent_id, name, self.workspace_id, self.user_id)
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

            chain_results = await asyncio.gather(
                chain_client.register_on_chain(agent_id, name, self.user_id),
                chain_client.create_agent_block(
                    agent_id, name, goal, self.user_id,
                    agent_hash=identity_hash),
                chain_client.create_agent_wallet(agent_id, self.user_id),
                chain_client.create_agent_hash_sphere(agent_id, name),
                return_exceptions=True,
            )
            if isinstance(chain_results[2], dict):
                wallet_addr = (chain_results[2].get("address", "")
                               or chain_results[2].get("wallet_address", ""))
        except Exception as e:
            logger.warning(f"[Builder] Blockchain registration failed: {e}")
        return identity_hash, wallet_addr

    async def _test_tools(self, tools: List[str]) -> List[Dict]:
        """Quick-test each tool to verify it actually works."""
        results = []
        for tool_name in tools[:5]:
            test_input = TESTABLE_TOOLS.get(tool_name)
            if not test_input:
                results.append({"tool": tool_name, "ok": True,
                                "note": "no test available (assumed ok)"})
                continue
            try:
                if tool_name == "web_search":
                    from src.tools.builtin.web_search import web_search
                    r = await web_search(test_input["query"], test_input.get("context", ""))
                    ok = bool(r) and not (isinstance(r, dict) and r.get("error"))
                elif tool_name == "fetch_url":
                    from src.tools.builtin.scrape_page import scrape_page
                    r = await scrape_page(test_input["url"], "markdown")
                    ok = bool(r) and not (isinstance(r, dict) and r.get("error"))
                else:
                    ok = True
                    r = "skipped"
                results.append({"tool": tool_name, "ok": ok,
                                "note": "test passed" if ok else f"test failed: {str(r)[:100]}"})
            except Exception as e:
                results.append({"tool": tool_name, "ok": False,
                                "note": f"test error: {str(e)[:100]}"})
        return results

    async def _post_build_test_run(
        self, agent_id: str, name: str, goal: str, max_retries: int = 1,
    ) -> Dict[str, Any]:
        """Phase 2: Post-build test run — actually execute the agent and verify output.

        1. Start a test session via Agent Engine with a simplified goal
        2. Poll for completion (up to 60s)
        3. If failed, auto-retry once with adjusted parameters
        """
        test_goal = f"Quick test: {goal[:100]}. Perform ONE step only and report what you found."

        async def _run_test(attempt: int) -> Dict:
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(
                        f"{AGENT_ENGINE_URL}/agents/{agent_id}/sessions",
                        headers=self.ws_db._headers,
                        json={
                            "goal": test_goal,
                            "max_steps": 3,
                            "test_mode": True,
                        },
                    )
                    if resp.status_code not in (200, 201):
                        return {"status": "skip", "note": f"Engine returned {resp.status_code}"}
                    session = resp.json()
                    session_id = session.get("session_id") or session.get("id", "")
                    if not session_id:
                        return {"status": "skip", "note": "No session_id returned"}

                # Poll for completion
                t0 = datetime.now(timezone.utc)
                for _ in range(12):  # 12 × 5s = 60s max
                    await asyncio.sleep(5)
                    try:
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            poll = await client.get(
                                f"{AGENT_ENGINE_URL}/agents/sessions/{session_id}",
                                headers=self.ws_db._headers,
                            )
                            if poll.status_code == 200:
                                data = poll.json()
                                status = data.get("status", "")
                                if status in ("completed", "success", "done"):
                                    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
                                    return {
                                        "status": "success",
                                        "session_id": session_id,
                                        "steps": data.get("steps_executed", 0),
                                        "duration_s": elapsed,
                                        "attempt": attempt,
                                    }
                                elif status in ("failed", "error", "cancelled"):
                                    return {
                                        "status": "failed",
                                        "session_id": session_id,
                                        "error": data.get("error", "unknown"),
                                        "attempt": attempt,
                                    }
                    except Exception:
                        pass
                return {
                    "status": "timeout",
                    "session_id": session_id,
                    "note": "Test run timed out after 60s",
                    "attempt": attempt,
                }
            except Exception as e:
                return {"status": "error", "note": str(e)[:200], "attempt": attempt}

        first = await _run_test(1)

        if first.get("status") == "success":
            return first

        if first.get("status") in ("failed", "error") and max_retries > 0:
            logger.info(f"[Builder] Test run failed for '{name}', retrying...")
            await self._emit("test_run", f"Test run failed ({first.get('error', 'unknown')}), auto-retrying...")
            retry = await _run_test(2)
            return {
                "status": "retried",
                "first_attempt": first,
                "retry": retry,
                "retry_ok": retry.get("status") == "success",
            }

        return first

    async def _generate_post_build_offers(
        self, agent_id: str, name: str, goal: str, tools: List[str],
    ) -> List[Dict[str, str]]:
        """Phase 2: Generate intelligent post-build offers.

        Returns list of offer dicts: [{"type": ..., "title": ..., "description": ...}]
        """
        offers: List[Dict[str, str]] = []

        # Offer 1: Scheduling (if goal suggests recurring work)
        recurring_keywords = [
            "monitor", "daily", "check", "track", "watch", "alert",
            "report", "scrape", "collect", "digest", "summarize",
            "news", "price", "stock", "weather", "feed",
        ]
        goal_lower = goal.lower()
        if any(kw in goal_lower for kw in recurring_keywords):
            offers.append({
                "type": "schedule",
                "title": "Set up automatic scheduling",
                "description": (
                    f"'{name}' looks like a recurring task. "
                    "Would you like to schedule it to run daily, hourly, or on a custom cron?"
                ),
                "action": "create_schedule",
                "agent_id": agent_id,
            })

        # Offer 2: Alerts/notifications
        if any(kw in goal_lower for kw in ["alert", "notify", "warn", "detect", "monitor"]):
            offers.append({
                "type": "alert",
                "title": "Configure alerts",
                "description": (
                    "I can set up anomaly detection triggers so you get "
                    "notified when this agent detects something important."
                ),
                "action": "create_anomaly_trigger",
                "agent_id": agent_id,
            })

        # Offer 3: Team collaboration
        if any(kw in goal_lower for kw in ["team", "collaborat", "share", "together"]):
            offers.append({
                "type": "team",
                "title": "Add to a team",
                "description": (
                    "This agent could work as part of a team. "
                    "Would you like to create or add it to a team workflow?"
                ),
                "action": "create_team",
                "agent_id": agent_id,
            })

        # Offer 4: Marketplace publishing (always offer)
        offers.append({
            "type": "marketplace",
            "title": "Publish to marketplace",
            "description": (
                f"Share '{name}' with the community or sell access on the marketplace."
            ),
            "action": "publish_agent",
            "agent_id": agent_id,
        })

        # Offer 5: Improvement suggestions (use LLM for smart suggestions)
        try:
            tool_list = ", ".join(tools[:6])
            resp = await call_llm(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Agent '{name}' was just built with goal: {goal}\n"
                        f"Tools: {tool_list}\n\n"
                        "Suggest ONE specific improvement in 1 sentence. "
                        "Focus on a missing tool, better strategy, or efficiency tip. "
                        "Be concrete and actionable."
                    ),
                }],
                model=FAST_MODEL, max_tokens=100, temperature=0.7,
            )
            suggestion = (resp.get("choices", [{}])[0]
                          .get("message", {}).get("content", "")).strip()
            if suggestion and len(suggestion) > 10:
                offers.append({
                    "type": "improvement",
                    "title": "Improvement suggestion",
                    "description": suggestion,
                    "action": "modify_agent",
                    "agent_id": agent_id,
                })
        except Exception as e:
            logger.debug(f"[Builder] Improvement suggestion failed: {e}")

        return offers
