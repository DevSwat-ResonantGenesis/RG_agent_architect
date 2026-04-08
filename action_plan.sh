#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# RG AGENT ARCHITECT — FULL ARCHITECTURE REWRITE ACTION PLAN
# Target: Match Twin's orchestrator quality, intelligence, and autonomy
# ═══════════════════════════════════════════════════════════════════════════
#
# REFERENCE: twin.md (Twin's full system prompt and architecture)
# REPO: /Users/louie/CascadeProjects/RG/RG_agent_architect/
#
# ═══════════════════════════════════════════════════════════════════════════
# DIAGNOSIS — WHY CURRENT ARCHITECTURE IS BROKEN
# ═══════════════════════════════════════════════════════════════════════════
#
# 1. orchestrator.py:27  — MAX_TOOL_ITERATIONS=10, too few for complex flows
# 2. orchestrator.py:87  — max_tokens=2000, LLM can't think/plan properly
# 3. orchestrator.py:71  — Only 6 messages of history, loses context
# 4. orchestrator.py:75  — Truncates messages to 1000 chars, loses detail
# 5. config.py:26        — POLL_MAX_ROUNDS=5, only 15s of polling (agents need minutes)
# 6. config.py:25        — POLL_INTERVAL=3.0, too fast, wastes requests
# 7. prompts.py:467-612  — PLATFORM_PROMPT contradicts Twin's prompt above it
# 8. prompts.py:522-533  — "NEVER ask" conflicts with Twin's "confirm before build"
# 9. prompts.py:535-612  — BUILDER-QUALITY section is bolt-on patch, not integrated
# 10. prompts.py:189-273 — PLANNING_PROMPT is dead code (not used by ReAct loop)
# 11. prompts.py:279-303 — BRAINSTORM_PROMPT is dead code (not used by ReAct loop)
# 12. tools.py            — Only 16 tools. Twin has 21. Missing critical ones:
#                           workspace_snapshot, agent_snapshot, run_snapshot,
#                           get_user_memory, update_user_memory, present_options (proper),
#                           get_credits_info, get_current_time
# 13. tool_executor.py    — No implementations for missing tools
# 14. context.py:57-59    — Only passes tool COUNT, not names/descriptions
# 15. builder.py          — ENTIRE FILE is dead code, not used by ReAct loop
# 16. builder.py:105      — build_safety_config defaults max_loops=25 (too low)
# 17. runner.py            — POLL_MAX_ROUNDS inherited from config (5 = 15 seconds)
#
# ═══════════════════════════════════════════════════════════════════════════
# FILE MAP — EVERY FILE THAT MUST CHANGE
# ═══════════════════════════════════════════════════════════════════════════
#
# FILE                                                    LINES  ACTION
# /app/config.py                                           39    REWRITE — fix polling, timeouts
# /app/services/prompts.py                                627    REWRITE — single coherent prompt
# /app/services/tools.py                                  400    REWRITE — add all 21 tools
# /app/services/tool_executor.py                          784    REWRITE — add all tool implementations
# /app/services/orchestrator.py                           286    REWRITE — increase iterations/tokens/context
# /app/services/context.py                                107    REWRITE — full tool list with descriptions
# /app/services/builder.py                                381    CLEAN UP — remove dead code
# /app/services/runner.py                                 247    FIX — polling config
# /app/routers.py                                        111    MINOR FIX — remove dead import
#
# ═══════════════════════════════════════════════════════════════════════════
# EXECUTION ORDER (dependencies matter)
# ═══════════════════════════════════════════════════════════════════════════
#
# PHASE 1: Foundation
#   [1] config.py         — All other files depend on these settings
#   [2] context.py        — Orchestrator depends on this for workspace data
#
# PHASE 2: Intelligence Layer
#   [3] prompts.py        — Complete system prompt rewrite
#   [4] tools.py          — All 21 tool schemas
#   [5] tool_executor.py  — All 21 tool implementations
#
# PHASE 3: Orchestration
#   [6] orchestrator.py   — ReAct loop upgrade
#   [7] builder.py        — Remove dead code
#   [8] runner.py         — Fix polling
#   [9] routers.py        — Clean imports
#
# PHASE 4: Deploy
#   [10] git add + commit + push
#   [11] SSH → git pull → docker rebuild
#   [12] Verify container health
#
# ═══════════════════════════════════════════════════════════════════════════
# SPECIFIC CHANGES PER FILE
# ═══════════════════════════════════════════════════════════════════════════
#
# ── config.py (line-by-line) ──
# Line 24: EXECUTION_TIMEOUT 120 → 180
# Line 25: POLL_INTERVAL 3.0 → 5.0
# Line 26: POLL_MAX_ROUNDS 5 → 40 (5*40=200s = 3.3 min polling)
# ADD: ORCHESTRATOR_MAX_TOKENS = 4096
# ADD: ORCHESTRATOR_MAX_ITERATIONS = 20
# ADD: ORCHESTRATOR_HISTORY_DEPTH = 10
#
# ── context.py (full rewrite of _fetch_tools) ──
# Line 48-61: _fetch_tools only gets count → must get FULL tool list with names + descriptions
# Must return structured dict: {category: [{name, description}]}
# Must include OAuth scope annotations
# Line 63-77: _fetch_memory must return structured facts, not raw concat
#
# ── prompts.py (MAJOR REWRITE) ──
# KEEP: INTENT_CLASSIFY_PROMPT (lines 10-24) — still useful for routing
# KEEP: IDENTITY_PROMPT (lines 30-36) — good as-is (already adapted from Twin)
# KEEP: SYSTEM_PROMPT (lines 38-49) — good as-is
# KEEP: MODES_PROMPT (lines 51-144) — Twin's modes, already good
# KEEP: LIFECYCLE_PROMPT (lines 146-162) — good progression rules
# KEEP: STYLE_PROMPT (lines 164-183) — good style rules
# DELETE: PLANNING_PROMPT (lines 189-273) — dead code, not used by ReAct
# DELETE: BRAINSTORM_PROMPT (lines 279-303) — dead code, not used by ReAct
# DELETE: MODIFY_PROMPT (lines 309-331) — dead code, not used by ReAct
# KEEP: SCOPE RISK patterns (lines 337-351) — useful for regex matching
# KEEP: GOAL_CRAFTING_PROMPT (lines 357-438) — used for goal crafting
# KEEP: USER_FACTS_PROMPT (lines 445-460) — used for memory extraction
# REWRITE: PLATFORM_PROMPT (lines 467-612) — remove contradictions, align with Twin
#   - Remove "AUTONOMOUS EXECUTION PROTOCOL" that contradicts Twin's confirm-first
#   - Remove "BUILDER-QUALITY AGENT CRAFTING" bolt-on — integrate into main flow
#   - Add proper tool descriptions matching our actual tool surface
#   - Add present_options usage instructions
#   - Add scope_warning format
#   - Add run_events handling
# REWRITE: build_system_prompt() (lines 614-626) — cleaner assembly
#
# ── tools.py (ADD MISSING TOOLS) ──
# KEEP: list_agents, get_agent_details, delete_agent, create_agent, run_agent,
#       modify_agent, schedule_agent, stop_agent, get_agent_sessions,
#       list_platform_tools, set_agent_budget, check_agent_wallet,
#       auto_build_tool, check_tool_exists, execute_built_tool,
#       health_check_agents, respond_to_user
# ADD: workspace_snapshot — parallel fetch of agents + tools + memory (like Twin's init)
# ADD: agent_snapshot — deep inspect with instructions, runs, config
# ADD: run_snapshot — full trace of a single run
# ADD: get_user_memory — recall user facts
# ADD: update_user_memory — store user facts
# ADD: present_options — show choices to user (PickOne/PickMultiple/OpenEnded/Secret)
# ADD: get_credits_info — check user credit balance
# ADD: get_current_time — current timestamp in user timezone
#
# ── tool_executor.py (ADD IMPLEMENTATIONS) ──
# ADD: _workspace_snapshot() — calls 3 APIs in parallel (agents + tools + memory)
# ADD: _agent_snapshot() — GET /agents/{id} + sessions + instructions
# ADD: _run_snapshot() — GET /execution/history/{agent_id}/{session_id}
# ADD: _get_user_memory() — POST /memory/search
# ADD: _update_user_memory() — POST /memory/ingest
# ADD: _present_options() — returns structured JSON for frontend rendering
# ADD: _get_credits_info() — GET /credits/balance or /billing/info
# ADD: _get_current_time() — returns current UTC time
#
# ── orchestrator.py (CRITICAL FIXES) ──
# Line 27: MAX_TOOL_ITERATIONS 10 → 20
# Line 87: max_tokens 2000 → 4096
# Line 71: prev_msgs[-6:] → prev_msgs[-10:]
# Line 75: content[:1000] → content[:2000]
# Line 117-118: present_options handling — must return structured response
# ADD: Handle present_options tool call as semi-terminal (returns to user with options)
# ADD: Better context block with full tool names
#
# ── builder.py (CLEANUP) ──
# This file is dead code from old non-ReAct architecture.
# KEEP: build_safety_config (used by tool_executor)
# KEEP: create_single_agent (backup)
# DELETE or DEPRECATE: generate_blueprint, generate_brainstorm, 
#   create_agents_from_blueprint (all replaced by ReAct loop)
# FIX: build_safety_config line 105 max_loops 25 → 30
#
# ── runner.py ──
# No code changes needed — it reads from config.py which we fix in Phase 1
#
# ── routers.py ──
# Line 66-68: classify_intent_endpoint imports _classify_intent which doesn't exist
#   in orchestrator.py (dead endpoint from old arch). Either remove or add stub.
#
# ═══════════════════════════════════════════════════════════════════════════
# DEPLOY COMMANDS
# ═══════════════════════════════════════════════════════════════════════════

echo "=== Phase 4: Deploy ==="
cd /Users/louie/CascadeProjects/RG/RG_agent_architect

# Step 1: Commit and push
git add -A
git commit -m "FULL ARCHITECTURE REWRITE: Match Twin's orchestrator quality

- config.py: Fix polling (40 rounds), timeouts (180s), add orchestrator constants
- prompts.py: Remove contradictions, single coherent Twin-quality prompt
- tools.py: Add 8 missing tools (workspace_snapshot, agent_snapshot, run_snapshot,
  get_user_memory, update_user_memory, present_options, get_credits_info, get_current_time)
- tool_executor.py: Add implementations for all new tools
- orchestrator.py: 20 iterations, 4096 tokens, 10 msg history, present_options handling
- context.py: Full tool list with names/descriptions, not just count
- builder.py: Fix max_loops default, deprecate dead code
- routers.py: Fix dead classify_intent import"
git push origin main

# Step 2: Deploy on server
ssh deploy@134.199.221.149 << 'EOF'
cd /home/deploy/RG_agent_architect
git fetch origin
git reset --hard origin/main
sudo docker compose -f /home/deploy/docker-compose.unified.yml up -d --build agent_architect_service
sleep 5
curl -s http://localhost:8000/architect/health | python3 -m json.tool
EOF

echo "=== Deploy complete ==="
