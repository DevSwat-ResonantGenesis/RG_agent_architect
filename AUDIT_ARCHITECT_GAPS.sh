#!/bin/bash
# ============================================================================
# AGENT ARCHITECT — FULL AUDIT: Tools, Gaps, and Intelligence Plan
# Generated: 2026-04-22
# ============================================================================

# ============================================================================
# 1. LOGS ANALYSIS — What's failing and why
# ============================================================================
#
# FROM PRODUCTION LOGS (agent_architect container):
#
# [ERROR 1] run_agent → "No instructions — build first"
#   Agent had no system_prompt. The architect tried to run before building.
#   Root cause: LLM called run_agent before build_agent completed.
#
# [ERROR 2] OpenAI 401 + Anthropic 401
#   WARNING rg_llm.client: openai:sk-proj- marked as failed (cooldown 30s)
#   WARNING rg_llm.client: anthropic/claude-sonnet-4-20250514 failed: 401 Unauthorized
#   → API keys expired or invalid. Only Groq works.
#
# [ERROR 3] 402 insufficient_credits on save_run
#   WARNING src.builder.builder: save_run failed: Credits exhausted
#   → Agent gets BUILT but run record fails. Agent exists but is "orphaned".
#
# [ERROR 4] Memory 404
#   WARNING src.services.memory.memory_store: /rag/memories → 404
#   → Memory service RAG endpoint not responding.
#

# ============================================================================
# 2. ALL 42 ARCHITECT ORCHESTRATOR TOOLS
# ============================================================================
#
# ── Workspace ──
# 1.  workspace_snapshot         — Get all agents and workspace state
# 2.  list_workspace_tools       — List available tools for agents
# 3.  set_workspace_name         — Rename workspace
# 4.  list_workspace_databases   — List per-agent databases
#
# ── Memory ──
# 5.  get_user_memory            — Get stored user preferences
# 6.  update_user_memory         — Store a user fact
# 7.  get_agent_memory           — Get agent-specific hash sphere memory
# 8.  get_dual_memory            — Get combined user + agent memory
# 9.  ask_memory                 — Ask a question to RAG memory
#
# ── Agent Snapshots ──
# 10. agent_snapshot             — Get agent details + recent runs + blockchain
# 11. run_snapshot               — Get run details
#
# ── Build / Run / Modify ──
# 12. build_agent                — Create a new agent (classify → generate prompt → save → blockchain → test tools)
# 13. continue_build             — Update agent instructions
# 14. message_build              — Refine agent via natural language
# 15. run_agent                  — Execute an agent (delegates to Agent Engine)
# 16. stop_run                   — Stop an active run
# 17. delete_agent               — Delete agent
# 18. delete_all_agents          — Delete ALL agents
# 19. modify_agent               — Add/remove tools, update config
#
# ── Scheduling ──
# 20. set_trigger                — Schedule agent (minutely/hourly/daily/weekly) [BASIC]
# 21. create_schedule            — Create cron schedule via Agent Engine [ADVANCED]
#
# ── Billing ──
# 22. get_credits_info           — Get wallet/credits/plan
# 23. check_credits              — Check if enough credits
#
# ── Integrations ──
# 24. check_integrations         — Check connected OAuth providers
# 25. get_agent_settings         — Get agent-specific settings
#
# ── Blockchain ──
# 26. get_agent_chain_status     — Get blockchain identity status
#
# ── Prompt Management ──
# 27. get_agent_prompt           — Read system prompt
# 28. update_agent_prompt        — Write/replace system prompt
#
# ── Agent Config ──
# 29. update_agent_config        — Update model/temperature/tools/mode etc
#
# ── Sessions / History ──
# 30. get_agent_sessions         — Get recent sessions
# 31. get_session_steps          — Get step-by-step trace
#
# ── Delegation ──
# 32. delegate_to_agent          — Run any agent as sub-task (by ID)
# 33. delegate_by_name           — Run any agent as sub-task (by name)
#
# ── Planning / TODO ──
# 34. create_task                — Create TODO task
# 35. list_tasks                 — List TODO tasks
# 36. update_task                — Update task status
# 37. brainstorm                 — Store brainstorm idea
# 38. get_workspace_plan         — Get full workspace plan
#
# ── Self-Learning ──
# 39. store_insight              — Store learned pattern
# 40. retrieve_architect_context — Get accumulated knowledge
#
# ── Other ──
# 41. present_options            — Show user choices
# 42. get_current_time           — UTC timestamp
#

# ============================================================================
# 3. GAP ANALYSIS: Agent Engine Endpoints vs Architect Tools
# ============================================================================
#
# AGENT ENGINE HAS ~80 ENDPOINTS. ARCHITECT HAS ACCESS TO ~15 OF THEM.
#
# ┌─────────────────────────────────┬──────────┬───────────────────────────┐
# │ Agent Engine Endpoint           │ Architect│ Notes                     │
# │                                 │ Has Tool?│                           │
# ├─────────────────────────────────┼──────────┼───────────────────────────┤
# │ POST /agents (create)           │ ✓ build  │ Via builder, not direct   │
# │ GET /agents (list)              │ ✓ snap   │ Via workspace_snapshot    │
# │ GET /agents/{id}                │ ✓ snap   │ Via agent_snapshot        │
# │ PATCH /agents/{id}              │ ✓        │ update_agent_config       │
# │ DELETE /agents/{id}             │ ✓        │ delete_agent              │
# │ POST /agents/{id}/sessions      │ ✓        │ run_agent                 │
# │ GET /agents/{id}/sessions       │ ✓        │ get_agent_sessions        │
# │ GET /sessions/{id}/steps        │ ✓        │ get_session_steps         │
# │ POST /sessions/{id}/cancel      │ ✗ !!!    │ MISSING — can't cancel    │
# │ POST /{id}/emergency-stop       │ ✗ !!!    │ MISSING — can't kill switch│
# │ POST /sessions/{id}/approve     │ ✗ !!!    │ MISSING — can't approve   │
# │ POST /agents/{id}/schedules     │ ✓        │ create_schedule           │
# │ GET /agents/{id}/schedules      │ ✗        │ MISSING — can't list      │
# │ PATCH /schedules/{id}           │ ✗        │ MISSING — can't update    │
# │ DELETE /schedules/{id}          │ ✗        │ MISSING — can't delete    │
# │ POST /{id}/triggers             │ ✗        │ MISSING                   │
# │ GET /{id}/triggers              │ ✗        │ MISSING                   │
# │ GET /metrics                    │ ✗        │ MISSING — no analytics    │
# │ GET /metrics/summary            │ ✗        │ MISSING                   │
# │ GET /{id}/metrics               │ ✗        │ MISSING                   │
# │ GET /available-tools            │ ✗        │ MISSING — sees 13 not 74  │
# │ POST /tools/execute             │ ✗ !!!    │ MISSING — can't test tools│
# │ GET /tools/list (full 74)       │ ✗ !!!    │ MISSING — only knows 13   │
# │ POST /tools/classifier/predict  │ ✗        │ MISSING                   │
# │ GET /templates                  │ ✗        │ MISSING                   │
# │ POST /templates/{id}/instantiate│ ✗        │ MISSING                   │
# │ PATCH /{id}/mode                │ ✗        │ MISSING                   │
# │ GET /{id}/versions              │ ✗        │ MISSING                   │
# │ GET /{id}/collective-knowledge  │ ✗        │ MISSING                   │
# │ GET /capabilities               │ ✗        │ MISSING                   │
# │ GET /providers                  │ ✗        │ MISSING                   │
# │ POST /sessions/{id}/feedback    │ ✗        │ MISSING                   │
# │ GET /approvals/pending          │ ✗        │ MISSING                   │
# │ POST /governance/evaluate       │ ✗        │ MISSING                   │
# │ GET /sessions/{id}/sse          │ ✗ !!!    │ MISSING — can't stream    │
# │ POST /{id}/publish              │ ✗        │ MISSING                   │
# │ POST /{id}/publish-api          │ ✗        │ MISSING                   │
# │ POST /repo-to-agent             │ ✗        │ MISSING                   │
# │ POST /repo-to-agent/analyze     │ ✗        │ MISSING                   │
# │ PATCH /{id}/unarchive           │ ✗        │ MISSING                   │
# │ GET /learning/*                 │ ✗        │ MISSING                   │
# │ POST /anomaly-triggers          │ ✗        │ MISSING                   │
# │ GET /compliance/*               │ ✗        │ MISSING                   │
# │ GET /governance/*               │ ✗        │ MISSING                   │
# └─────────────────────────────────┴──────────┴───────────────────────────┘
#
# CRITICAL MISSING (blocks basic operations):
# 1. cancel_session      — Cannot stop a running session
# 2. emergency_stop      — Cannot kill switch an agent
# 3. approve_step        — Cannot approve pending actions
# 4. list_all_tools      — Only sees 13 tools, Agent Engine has 74+
# 5. execute_tool_direct — Cannot test tools before assigning
# 6. session_sse_stream  — Cannot monitor execution in real-time
# 7. list_schedules      — Cannot see existing schedules
# 8. delete_schedule     — Cannot remove schedules
# 9. get_metrics         — Cannot check agent performance
# 10. list_providers     — Cannot verify which LLM providers are available
#

# ============================================================================
# 4. INTELLIGENCE GAPS — Why Architect is "dumb"
# ============================================================================
#
# CURRENT FLOW (broken):
#   User: "Create agent X"
#   Architect: build_agent(name, goal, tools=[web_search])  # that's it
#
# WHAT IT SHOULD DO (autonomous professional pipeline):
#
#   1. RESEARCH PHASE
#      - Analyze the user request deeply
#      - check_integrations() — what's connected?
#      - list_providers() — which LLM providers respond?
#      - get_credits_info() — can user afford this?
#      - ask_memory() — any past context about this type of agent?
#      - retrieve_architect_context() — any patterns learned?
#
#   2. PLANNING PHASE
#      - Determine agent type (scraper, monitor, automation, research...)
#      - Select optimal model (Groq for speed, GPT-4o for quality, Claude for analysis)
#      - Select optimal tools from FULL 74-tool registry (not just 13)
#      - Use tools/classifier/predict to get neural recommendations
#      - Plan the system prompt with domain expertise
#      - Create execution strategy (loops, temperature, safety config)
#
#   3. PROVIDER VERIFICATION PHASE
#      - Actually test the selected LLM provider: send a test message
#      - If provider fails (401/timeout), try next provider
#      - If all fail, tell user which API keys need setup
#      - Verify tool connectivity (OAuth integrations)
#
#   4. BUILD PHASE
#      - Build agent with verified configuration
#      - Register blockchain identity
#      - Test each tool with execute_tool_direct
#
#   5. TEST PHASE (NEW — doesn't exist)
#      - run_agent with a test goal
#      - Monitor via SSE stream
#      - Check session outcome
#      - If failed: analyze steps, adjust prompt, retry
#      - If succeeded: store as pattern for future
#
#   6. POST-BUILD PHASE (NEW — doesn't exist)
#      - Ask user: "Want to schedule this? Add more tools?"
#      - Offer to set up monitoring/alerts
#      - Store learnings for next time
#      - Suggest improvements based on similar agents
#
# NONE OF THIS EXISTS. The architect just calls build_agent() and hopes for the best.
#

# ============================================================================
# 5. ACTION PLAN — Priority fixes
# ============================================================================
#
# PHASE 1: Critical tool gaps — COMPLETED 2026-04-22
# [x] Add cancel_session tool
# [x] Add emergency_stop tool
# [x] Add approve_step tool
# [x] Add get_pending_approvals tool
# [x] Add list_engine_tools (full 74-tool registry)
# [x] Add execute_tool (test any tool directly)
# [x] Add list_providers (check which LLMs work)
# [x] Add list_schedules
# [x] Add get_agent_metrics
#
# PHASE 1b: Neural Tool Classifier — COMPLETED 2026-04-22
# [x] ArchitectToolClassifier: groups 53 tools into 8 intent clusters
# [x] 180+ synthetic training samples
# [x] Smart injection: only send relevant tools per message (not all 53)
# [x] Keyword fallback when neural model unavailable
# [x] Builder: neural tool selection from Agent Engine's /tools/classifier/predict
#     (74+ tools) instead of hardcoded 13
#
# PHASE 1c: FULL Engine Coverage — COMPLETED 2026-04-22
# [x] 125 tool definitions (was 51) — covers ALL 101 Agent Engine endpoints
# [x] 128 tool handlers — generic _engine_api() helper for clean HTTP proxy
# [x] 14 classifier groups (was 8) + none: build, run, schedule, inspect,
#     memory, plan, delegate, workspace, teams, marketplace, federation,
#     governance, learning, advanced
# [x] 223 training samples (was 180)
# [x] Agent Engine tool registry confirmed at 161 tools (not 74)
# [x] New endpoint categories: triggers, anomaly, sessions (deep), versions,
#     mode, templates, federation, governance, compliance, teams, marketplace,
#     publishing, learning, limits, capabilities, watchdog, repo-to-agent
#
# PHASE 1d: Classifier Training & Verification — COMPLETED 2026-04-22
# [x] ArchitectToolClassifier now trains at STARTUP (was lazy/never)
# [x] Added _preload_tool_classifier() to lifespan in main.py
# [x] Added /api/tool-classifier/stats and /api/tool-classifier/predict endpoints
# [x] Verified in production: 15 groups, 223 samples, accuracy=0.8341
# [x] All 14 groups classify correctly (build, teams, marketplace, etc.)
# [x] Agent Engine classifier: rebuilt container (tool_classifier/ was missing!)
# [x] Agent Engine: 203 tools, 1030 samples, accuracy=0.8874, model v1 saved to DB
# [x] Agent Engine: auto-detected stale model (200→203 classes), retrained
#
# PHASE 2: Intelligence pipeline — COMPLETED 2026-04-22
# [x] Pre-build research: 4 parallel checks (credits, integrations, provider, memory)
#     - Credits: blocks build if exhausted, warns if < 100 remaining
#     - Integrations: queries Agent Engine /agents/integrations
#     - Memory: asks RAG "any past experience building agents for [goal]"
#     - All run in asyncio.gather() — no serial blocking
# [x] Provider health check: sends "Reply with OK" to assigned model
#     - If empty or error → auto-switches to DEFAULT_MODEL fallback
#     - Warning emitted via SSE so user sees the switch
# [x] Post-build test run + auto-retry:
#     - Creates test session via /agents/{id}/sessions (max_steps=3, test_mode=True)
#     - Polls /agents/sessions/{id} every 5s for up to 60s
#     - On failure: auto-retries once, reports both attempts
#     - On success: reports steps + duration
# [x] Post-build offers: intelligent suggestions based on goal keywords
#     - Schedule: detected via "monitor", "daily", "track", "alert", etc.
#     - Alerts: detected via "alert", "notify", "detect", "monitor"
#     - Team: detected via "team", "collaborat", "share"
#     - Marketplace: always offered
#     - Improvement: LLM-generated 1-sentence suggestion (FAST_MODEL)
# Files changed: src/builder/builder.py (new methods: _pre_build_research,
#   _post_build_test_run, _generate_post_build_offers; removed dead json import)
#
# PHASE 3: SSE streaming integration — TODO
# [ ] Connect to /sessions/{id}/sse to monitor execution live
# [ ] Stream progress back to user through architect's SSE
# [ ] React to failures in real-time, auto-retry
#

echo "This is a report file. Read it, don't run it."
