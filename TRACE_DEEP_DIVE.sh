#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# RG_agent_architect — FULL PIPELINE TRACE & DEPENDENCY DEEP DIVE
# Generated: 2026-04-26
# ═══════════════════════════════════════════════════════════════════

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. SERVICE IDENTITY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Container:    agent_architect
# Port:         8000
# Framework:    FastAPI + SSE streaming
# Entrypoint:   src/api/main.py → uvicorn
# LLM Client:   UnifiedLLMClient (rg_llm volume mount)
# Database:     NONE own DB — uses Agent Engine API for all persistence
# Lines of code (approx):
#   orchestrator.py   ~856 lines (ReAct loop + build pipeline)
#   tool_executor.py  ~770 lines (100+ tool handlers)
#   builder.py        ~36K (multi-phase agent builder)
#   runner.py         ~257 lines (Agent Engine delegation + fallback)
#   tools.py (models) ~334 lines (101 tool definitions)
#   26 prompt modules  in src/prompts/modules/

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. STARTUP SEQUENCE (src/api/main.py lifespan)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. ML model DB tables: ensure_tables() (if DATABASE_URL available)
# 2. Prompt Router: preload_prompt_router()
#      - Neural classifier selects which prompt modules to compose
#      - Trained from src/prompts/training_data.py
# 3. Agent Type Classifier: preload_agent_type_classifier()
#      - Classifies agent goal → neural type (researcher, coder, creative, etc.)
#      - Used during build to generate specialized prompts
# 4. Tool Classifier: architect_tool_classifier.ensure_ready()
#      - Groups 101 ORCHESTRATOR_TOOLS into ~15 groups
#      - Only sends relevant tool subset per LLM call (saves tokens)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. API ENDPOINTS (src/api/main.py)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POST /api/message          — Sync JSON response (backward compat)
# POST /api/message/stream   — SSE streaming (primary — used by chat_service)
# POST /api/run-event        — Notify architect of agent run events
# GET  /api/workspace/{id}   — Get workspace state
# GET  /health               — Health check
# GET  /api/prompt-router/stats       — Neural prompt classifier stats
# POST /api/prompt-router/retrain     — Retrain prompt classifier
# GET  /api/agent-type-classifier/stats — Agent type classifier stats
# POST /api/agent-type-classifier/retrain — Retrain agent type classifier
# POST /api/agent-type-classifier/classify — Classify agent type (debug)
# GET  /api/tool-classifier/stats     — Tool classifier stats
# POST /api/tool-classifier/predict   — Predict tool group (debug)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. INCOMING CALL PATH (from chat_service)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# User → Frontend → Gateway → chat_service → agent_architect
#
# chat_service determines use_architect=True via:
#   1. Pipeline continuity (recent present_options)
#   2. Neural ToolClassifier (prediction == "agent_architect")
#   3. Regex keyword guard (_is_agent_intent)
#
# Then: POST http://agent_architect:8000/api/message/stream
#   Payload: {message, workspace_id, user_id, conversation_history[8], user_api_keys}
#   Headers: x-user-id, x-user-role, x-is-superuser, x-unlimited-credits
#   Response: SSE stream → forwarded live to frontend

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. ORCHESTRATOR FLOW (/api/message/stream)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# ┌─ handle_message_stream(message) ─────────────────────────────┐
# │                                                               │
# │  1. initialize_session()                                      │
# │     ├── fetch_workspace_context(workspace_id)                 │
# │     │     └── Agent Engine API: GET /agents/ → agent list     │
# │     └── get_user_api_keys(user_id) → BYOK keys from auth     │
# │                                                               │
# │  2. classify_mode(message, agents_exist)                      │
# │     → OperationMode: CONTROL | REVIEW | PLAN | REFINE         │
# │                                                               │
# │  3. Route to pipeline:                                        │
# │     ├── _start_build_pipeline() — if build intent detected    │
# │     ├── _continue_build_pipeline() — if pipeline active       │
# │     └── _run_loop(mode) — default ReAct loop                 │
# │                                                               │
# │  4. Yield SSE events: session_start → thinking → tool_call    │
# │     → tool_result → text → options → complete/error           │
# └───────────────────────────────────────────────────────────────┘

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. ReAct LOOP (_run_loop) — up to 8 iterations
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# for iteration in range(8):
#   ┌── STEP A: Build system prompt ──────────────────────────────┐
#   │  router.route(mode, message, context_block)                 │
#   │    ├── Neural prompt classifier → select relevant modules   │
#   │    │   Modules: agent_management, building, planning,       │
#   │    │   workspace, memory, economy, scheduling, safety, etc. │
#   │    └── Compose system prompt from selected modules          │
#   │         + context_block (agent list, credits, integrations) │
#   └─────────────────────────────────────────────────────────────┘
#
#   ┌── STEP B: Select tools (neural) ───────────────────────────┐
#   │  architect_tool_classifier.get_tools_for_message(message)   │
#   │    → predicted_group: "agent_management", "building",       │
#   │      "scheduling", "memory", "economy", "delegation",      │
#   │      "planning", "session", "tools_registry", etc.          │
#   │    → selected_tools: subset of 101 ORCHESTRATOR_TOOLS       │
#   │  Always includes: present_options, get_current_time,        │
#   │                   workspace_snapshot                         │
#   └─────────────────────────────────────────────────────────────┘
#
#   ┌── STEP C: LLM call ────────────────────────────────────────┐
#   │  call_llm(messages, tools=selected_tools)                   │
#   │    → UnifiedLLMClient → rg_llm → llm_service:8000          │
#   │    → Default model: groq/llama-3.3-70b-versatile            │
#   │    → BYOK keys forwarded if available                       │
#   └─────────────────────────────────────────────────────────────┘
#
#   ┌── STEP D: Process response ────────────────────────────────┐
#   │  If text only → emit "text" event, break                   │
#   │  If tool_calls → for each call:                            │
#   │    1. Safety check (safety.check_tool_args)                │
#   │    2. tool_executor.execute(name, args)                    │
#   │    3. Emit "tool_call" + "tool_result" SSE events          │
#   │    4. Inject result into messages as tool response          │
#   │    5. If TERMINAL tool (build_agent, modify_agent):         │
#   │       → LLM summary call → break                           │
#   │    6. If present_options → emit options, break              │
#   │    7. Repeat loop detection (break if same tool 3+ times)  │
#   └─────────────────────────────────────────────────────────────┘

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. BUILD PIPELINE (_start_build_pipeline) — 7 phases
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Phase 1: RESEARCH
#   ├── Check credits (billing_service)
#   ├── Check integrations (auth_service)
#   ├── Get existing agents (Agent Engine)
#   └── Warn if credits exhausted or integrations missing
#
# Phase 2: PLAN
#   ├── LLM generates: name, goal, icon, tools, model, temperature
#   ├── Neural agent type classification → specialized params
#   ├── Duplicate detection (fuzzy match against existing agents)
#   └── Risk analysis + recommendations
#
# Phase 3: VERIFY
#   ├── Test selected LLM provider health
#   ├── Verify tools are available
#   └── Fallback to groq/llama if provider down
#
# Phase 4: GENERATE PROMPT
#   ├── Specialized prompt writer (agent_type → prompt template)
#   ├── Inject tool documentation
#   └── Output: full system_prompt for the agent
#
# Phase 5: BUILD
#   ├── POST Agent Engine: save agent (name, goal, prompt, tools, model)
#   ├── Verify agent in DB
#   ├── Blockchain: register_agent_identity + create_agent_block
#   ├── Blockchain: create_agent_wallet
#   ├── Store run record
#   └── Store agent learning in memory
#
# Phase 6: TEST
#   ├── Runner.run(agent_id, goal) → Agent Engine session
#   ├── Poll session status
#   └── Report: success/fail, steps, duration
#
# Phase 7: OFFERS
#   ├── Generate post-build actions (run, schedule, modify, connect)
#   └── Present as interactive options to user

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. RUNNER (src/runner/runner.py) — Agent Execution
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Runner.run(agent_id, goal):
#   1. Get agent from Agent Engine
#   2. Check credits (billing_service)
#   3. PRIMARY: _run_via_agent_engine()
#      ├── POST http://agent_engine_service:8000/agents/{id}/sessions
#      │     (Agent Engine has 50+ tools: web, file, code, email, etc.)
#      ├── Poll session status (max 40 rounds × 5s = 200s)
#      ├── GET /agents/sessions/{id}/steps → step trace
#      └── Return: {summary, run_id, loops, status}
#   4. FALLBACK: _run_local_fallback()
#      ├── Local LLM loop with 4 basic tools:
#      │     web_search, scrape_page, store_result, done
#      ├── Max 30 loops
#      └── Used only if Agent Engine unreachable
#   5. Store run summary as learning (memory_service)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 9. TOOL EXECUTOR — 101 TOOLS IN 16 CATEGORIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Category              Tools  Implementation
# ──────────────        ─────  ──────────────
# Workspace             4      Local (WorkspaceDB → Agent Engine)
# Memory                5      MemoryStore → memory_service HTTP
# Agent Snapshots       2      WorkspaceDB + chain_client
# Build/Run             8      Builder + Runner + WorkspaceDB
# Scheduling            4      Agent Engine /schedules
# Billing/Economy       2      billing_client HTTP
# Integrations/OAuth    2      integration_client → auth_service
# Blockchain            1      chain_client → blockchain_service
# Prompt Management     2      Agent Engine PATCH /agents/{id}
# Agent Config          1      Agent Engine PATCH /agents/{id}
# Session History       2      Agent Engine /sessions
# Agent Delegation      2      Runner (spawn any agent)
# TODO/Planning         5      MemoryStore (RAG persistence)
# Session Control       4      Agent Engine /sessions/cancel, /approve
# Tool Registry         7      Agent Engine /tools
# Provider & Metrics    4      Agent Engine /providers, /metrics
# Schedules CRUD        3      Agent Engine /schedules
# Triggers/Webhooks     3      Agent Engine /triggers
# Anomaly Detection     4      Agent Engine /anomaly
# Session Inspection    4      Agent Engine /sessions deep
# Agent Versions        1      Agent Engine /versions
# Agent Mode            2      Agent Engine /agents/{id}
# Templates             2      Agent Engine /templates
# Federation            7      Agent Engine /federation
# Governance            6      Agent Engine /governance
# Teams                 14     Agent Engine /teams
# Marketplace           8      Agent Engine /marketplace
# Learning              4      Agent Engine /learning
# Limits/Capabilities   3      Agent Engine /limits
# Self-Learning         2      MemoryStore (architect insights)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 10. EXTERNAL SERVICE CONNECTIONS (13 services)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Service                  URL (Docker internal)                        Used For
# ───────────────────      ──────────────────────────────────────       ─────────────────
# agent_engine_service     http://agent_engine_service:8000             ALL agent CRUD, sessions, tools, schedules, teams, marketplace
# memory_service           http://memory_service:8000                   Hash sphere memory, RAG, user/agent memory, tasks, brainstorms
# billing_service          http://billing_service:8000                  Credits check, deduction, economic state
# blockchain_service       http://blockchain_service:8000               Agent identity, wallet, on-chain registration
# auth_service             http://auth_service:8000                     OAuth integrations, user API keys, agent settings
# notification_service     http://notification_service:8000             (config.py — not yet heavily used)
# code_execution_service   http://code_execution_service:8002           (config.py — for agent code tools)
# storage_service          http://storage_service:8000                  (config.py — file storage)
# workflow_service         http://workflow_service:8000                  (config.py — workflow orchestration)
# gateway                  http://gateway:8000                          (config.py — internal routing)
# sandbox_runner_service   http://sandbox_runner_service:9001           (config.py — sandboxed code execution)
# rg_ast_analysis          http://rg_ast_analysis:8000                  (config.py — code analysis)
# ed_service               http://ed_service:8000                       (config.py — education)
# llm_service              (via rg_llm UnifiedLLMClient)                ALL LLM calls (Groq, OpenAI, Anthropic, etc.)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 11. ML CLASSIFIERS (3 neural classifiers)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Prompt Router (src/prompts/router.py):
#   - sentence-transformers → prompt module selection
#   - 26 modules in src/prompts/modules/ (agent_management, building, etc.)
#   - Composes per-request system prompts from relevant modules
#   - Trained from src/prompts/training_data.py
#   - Persisted in DB (if available)
#
# Agent Type Classifier (src/builder/agent_type_classifier.py):
#   - Classifies agent goal → neural type
#   - Types: researcher, coder, writer, creative, analyst, scheduler, etc.
#   - Used during build to generate specialized system prompts
#   - Trained from src/builder/agent_type_training_data.py
#
# Tool Classifier (src/orchestrator/tool_classifier.py):
#   - Groups 101 tools into ~15 semantic groups
#   - Per-message tool selection (only send relevant tools to LLM)
#   - Reduces token usage by ~60-80% per call
#   - Fallback: regex-based TOOL_GROUPS if classifier not ready

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 12. DATA FLOW DIAGRAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# ┌─── Frontend (dev-swat.com) ──────────────────────┐
# │  User types: "build me a research agent"         │
# └──────────┬───────────────────────────────────────┘
#            │ POST /resonant-chat/message/stream
#            ▼
# ┌─── Gateway (nginx → gateway:8001) ──────────────┐
# │  Route: /resonant-chat/* → chat_service:8000     │
# └──────────┬───────────────────────────────────────┘
#            │
#            ▼
# ┌─── chat_service ────────────────────────────────┐
# │  1. Auth (crypto_identity / x-user-id)          │
# │  2. Store user message (PostgreSQL)              │
# │  3. Deduct credits (billing_service)             │
# │  4. Tool detection:                              │
# │     ├── ToolClassifier → "agent_architect"       │
# │     └── Regex guard → use_architect=True         │
# │  5. POST http://agent_architect:8000/            │
# │     api/message/stream (SSE)                     │
# │  6. Forward SSE events live to frontend          │
# │  7. Store assistant message (PostgreSQL)          │
# │  8. Background: ingest to memory_service          │
# └──────────┬───────────────────────────────────────┘
#            │ SSE stream
#            ▼
# ┌─── agent_architect ─────────────────────────────┐
# │  1. initialize_session()                         │
# │     ├── GET agent_engine/agents/ → agent list    │
# │     └── auth_service → BYOK keys                │
# │  2. Detect build intent → BuildPipeline          │
# │  3. Phase 1: RESEARCH                            │
# │     ├── billing_service: check credits           │
# │     ├── auth_service: check integrations         │
# │     └── agent_engine: existing agents            │
# │  4. Phase 2: PLAN (LLM call)                    │
# │     └── Neural agent type classifier             │
# │  5. Phase 3: VERIFY                              │
# │     └── Test LLM provider health                 │
# │  6. Phase 4: GENERATE PROMPT (LLM call)          │
# │     └── Specialized prompt writer                │
# │  7. Phase 5: BUILD                               │
# │     ├── agent_engine: POST /agents/ (create)     │
# │     ├── blockchain: register identity + wallet   │
# │     └── memory: store learning                   │
# │  8. Phase 6: TEST                                │
# │     ├── Runner → agent_engine: POST /sessions    │
# │     ├── Poll status (40 rounds × 5s)             │
# │     └── Report: success/fail                      │
# │  9. Phase 7: OFFERS                               │
# │     └── present_options → frontend buttons        │
# └──────────┬───────────────────────────────────────┘
#            │ When running an agent
#            ▼
# ┌─── agent_engine_service ────────────────────────┐
# │  POST /agents/{id}/sessions                      │
# │  - 50+ real tools (web, file, code, email, etc.) │
# │  - SSE streaming execution                       │
# │  - Step trace                                     │
# │  - Tool execution via custom_tools.py             │
# └──────────┬───────────────────────────────────────┘
#            │ Tool calls fan out to:
#            ▼
# ┌─── Platform Services ──────────────────────────┐
# │  memory_service    — RAG, hash sphere            │
# │  billing_service   — credit deduction            │
# │  blockchain_service — identity, wallet           │
# │  code_execution    — sandboxed code              │
# │  storage_service   — file storage                │
# │  External APIs     — Groq, OpenAI, Tavily, etc.  │
# └─────────────────────────────────────────────────┘

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 13. CONNECTION HEALTH — CRITICAL vs OPTIONAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# CRITICAL (service fails without these):
#   ✅ agent_engine_service  — ALL agent CRUD, sessions, tool execution
#   ✅ llm_service (via rg_llm) — ALL LLM calls
#
# IMPORTANT (degraded without these):
#   ⚠️ memory_service     — Memory, tasks, brainstorms (graceful fallback: empty)
#   ⚠️ billing_service    — Credit checks (fallback: has_credits=True)
#   ⚠️ auth_service       — BYOK keys, integrations (fallback: none)
#
# OPTIONAL (skipped if unavailable):
#   ℹ️ blockchain_service — On-chain registration (non-blocking)
#   ℹ️ notification_service — Alerts (not yet heavily used)
#   ℹ️ storage_service, code_execution_service, etc.

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 14. FILE INVENTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# src/api/
#   main.py              — FastAPI app, endpoints, SSE streaming
#
# src/core/
#   config.py            — 13 service URLs + tuning constants
#   llm_client.py        — UnifiedLLMClient wrapper (single entry point)
#   context.py           — fetch_workspace_context()
#
# src/orchestrator/
#   orchestrator.py      — Main ReAct loop + build pipeline (856 lines)
#   tool_executor.py     — 101 tool handlers (770 lines)
#   build_pipeline.py    — 7-phase autonomous build (24K)
#   tool_classifier.py   — Neural tool group classifier
#   tool_training_data.py — Training samples for tool classifier
#   safety.py            — Input/output safety checks
#   goal_crafter.py      — Goal refinement
#
# src/builder/
#   builder.py           — Multi-phase agent builder (36K)
#   specialised_prompt_writer.py — Type-specific prompt generation
#   agent_type_classifier.py — Neural agent type classifier
#   agent_type_training_data.py — Training samples
#
# src/runner/
#   runner.py            — Agent Engine delegation + local fallback
#
# src/models/
#   tools.py             — 101 ORCHESTRATOR_TOOLS definitions
#   agent.py             — OperationMode enum + agent models
#
# src/services/
#   database/workspace_db.py — Agent Engine API client
#   memory/memory_store.py   — Memory Service client (hash sphere, RAG, tasks)
#   billing/billing_client.py — Billing Service client
#   blockchain/chain_client.py — Blockchain Service client
#   auth/integration_client.py — Auth Service client (OAuth, keys)
#   email/                     — Email integration
#   file_ops/                  — File operations
#   ml_model_store.py          — PostgreSQL model persistence
#
# src/prompts/
#   router.py            — Neural prompt composition router
#   training_data.py     — Prompt router training samples
#   mode_classifier.py   — Mode classification (CONTROL/REVIEW/PLAN)
#   modules/ (26 files)  — Composable prompt modules
#
# src/tools/
#   builtin/             — web_search, scrape_page (fallback tools)
#   custom/              — Custom tool definitions
#   oauth/               — OAuth tool integration
#   scrapers/            — Web scraping tools

echo "RG_agent_architect trace complete. See above for full pipeline."
