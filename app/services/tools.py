"""
RG Agent Architect — Tool Definitions

All tool schemas the orchestrator LLM can call during the ReAct loop.
Derived from twin.md Section 2 (21 orchestrator tools) + platform extensions.

Tool categories:
1. Workspace & Context (workspace_snapshot, agent_snapshot, run_snapshot, list_agents,
   get_agent_details, list_platform_tools, list_workspace_databases, query_cross_agent_database)
2. Agent Lifecycle (create_agent, modify_agent, continue_build, message_build, delete_agent,
   run_agent, stop_agent, schedule_agent, set_agent_budget, check_agent_wallet)
3. User Interface (present_options, respond_to_user, present_billing_offer, open_interface_editor)
4. Utility (get_user_memory, update_user_memory, get_credits_info, get_current_time,
   set_workspace_name, configure_smtp, delete_smtp, file_operation)
5. Self-Extension (auto_build_tool, check_tool_exists, execute_built_tool)
6. Health (health_check_agents, get_agent_sessions)
"""

AGENT_TOOLS = [
    # ═══════════════════════════════════════════════════════════
    # 1. WORKSPACE & CONTEXT — Twin session_start + review tools
    # ═══════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "workspace_snapshot",
            "description": "Get a complete workspace overview: all agents with status, available platform tools, and user memory facts. Call at the START of every session before taking any action.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agent_snapshot",
            "description": "Deep inspect a specific agent: full config, system_prompt/instructions, recent run history with outcomes, tools assigned, budget status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Name of the agent to inspect"},
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_snapshot",
            "description": "Full trace of a single agent run: every decision, tool call, result, and error. Use to diagnose why a run failed or review what the agent did.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Name of the agent"},
                    "session_id": {"type": "string", "description": "Session/run ID. If omitted, uses most recent."},
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_agents",
            "description": "List all agents in the user's workspace with name, model, tools, status.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_agent_details",
            "description": "Get detailed info about a specific agent including recent sessions, status, tools, and config.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Name of the agent to inspect"},
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_platform_tools",
            "description": "List all available platform tools agents can use, organized by category. Call at session start (list_workspace_tools).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workspace_databases",
            "description": "List all agent SQLite databases in the workspace. Shows which agents have persistent data. Use before query_cross_agent_database.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_cross_agent_database",
            "description": "Execute a read-only SQL query against an agent's SQLite database. SELECT only. Use to inspect agent data or cross-reference between agents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Agent whose database to query"},
                    "query": {"type": "string", "description": "SQL SELECT query"},
                },
                "required": ["agent_name", "query"],
            },
        },
    },

    # ═══════════════════════════════════════════════════════════
    # 2. AGENT LIFECYCLE — Twin dispatching + builder/runner
    # ═══════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "create_agent",
            "description": "Create a new agent. You MUST provide detailed system_prompt with step-by-step INSTRUCTIONS. After creating, ALWAYS call run_agent immediately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Descriptive agent name"},
                    "description": {"type": "string", "description": "Clear 1-sentence purpose"},
                    "system_prompt": {"type": "string", "description": "CRITICAL: Detailed step-by-step instructions. Must include role, numbered steps with tool names, output format, storage, constraints."},
                    "goal": {"type": "string", "description": "Outcome-oriented goal in 2-3 sentences"},
                    "provider": {"type": "string", "enum": ["groq", "openai", "anthropic", "google"], "description": "LLM provider. Default: groq"},
                    "model": {"type": "string", "description": "Model name. Default: llama-3.3-70b-versatile"},
                    "tools": {"type": "array", "items": {"type": "string"}, "description": "Platform tool names this agent can use"},
                    "temperature": {"type": "number", "description": "LLM temperature. Default: 0.6"},
                    "mode": {"type": "string", "enum": ["governed", "supervised", "unbounded"], "description": "Autonomy mode. Default: governed"},
                    "max_loops": {"type": "integer", "description": "Max execution iterations. Default: 30. Set 30-50 for complex tasks."},
                    "budget": {
                        "type": "object",
                        "properties": {
                            "max_tokens_per_run": {"type": "integer", "description": "Max tokens per run. Default: 50000"},
                            "max_runs_per_day": {"type": "integer", "description": "Max runs/day. Default: 10"},
                            "initial_credits": {"type": "number", "description": "Initial credits. Default: 100.0"},
                        },
                    },
                },
                "required": ["name", "description", "system_prompt", "goal", "tools"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "continue_build",
            "description": "Modify/extend an existing agent via rebuild. Instructions MUST be a THREE-PART DELTA: what CHANGES, what STAYS, what STOPS. Twin dispatching: Extend → continue_build.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Agent to rebuild"},
                    "instructions": {"type": "string", "description": "3-part delta: CHANGES / STAYS / STOPS"},
                },
                "required": ["agent_name", "instructions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "message_build",
            "description": "Send guidance to an active build session. Twin dispatching: Guide → message_build. Queued if no active session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Agent with active build"},
                    "message": {"type": "string", "description": "Guidance for the builder"},
                },
                "required": ["agent_name", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify_agent",
            "description": "Update an existing agent's configuration — tools, model, goal, description, system prompt, or other settings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Agent to modify"},
                    "changes": {"type": "object", "description": "Key-value pairs: name, description, system_prompt, provider, model, temperature, tools, mode, is_active, max_loops, safety_config"},
                },
                "required": ["agent_name", "changes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_agent",
            "description": "Execute an agent immediately. ALWAYS call right after create_agent. Twin dispatching: Run → run_agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Agent to run"},
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_agent",
            "description": "Deactivate an agent. Does not delete. Confirm before stopping active runs (Twin proactive_defaults).",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Agent to stop"},
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_agent",
            "description": "Permanently delete an agent. Confirm before deleting (Twin proactive_defaults). Act immediately once confirmed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Agent to delete"},
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_agent",
            "description": "Set up automated recurring runs (set_trigger). Strip time language from goal; handle scheduling here.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Agent to schedule"},
                    "interval_seconds": {"type": "integer", "description": "Interval: 3600=hourly, 86400=daily, 604800=weekly"},
                    "cron_expression": {"type": "string", "description": "Cron expression (alternative to interval)"},
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_agent_budget",
            "description": "Set budget limits: max tokens/run, max runs/day, credit allocation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Agent to set budget for"},
                    "max_tokens_per_run": {"type": "integer"},
                    "max_runs_per_day": {"type": "integer"},
                    "credits": {"type": "number", "description": "Credits to allocate"},
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_agent_wallet",
            "description": "Check agent wallet balance and spending history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Agent to check"},
                },
                "required": ["agent_name"],
            },
        },
    },

    # ═══════════════════════════════════════════════════════════
    # 3. USER INTERFACE — Twin present_options, respond, billing
    # ═══════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "present_options",
            "description": "Show clickable choices to the user. SEMI-TERMINAL: stop loop after calling. Twin uses this for scope confirmations, brainstorm questions, follow-up actions. Supports PickOne/PickMultiple/OpenEnded/Secret types.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Question or prompt to show"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "Button text"},
                                "value": {"type": "string", "description": "Return value"},
                                "description": {"type": "string", "description": "Optional subtitle"},
                                "icon": {"type": "string", "description": "Optional emoji"},
                            },
                            "required": ["label", "value"],
                        },
                        "description": "2-4 clickable options",
                    },
                    "question_type": {"type": "string", "enum": ["PickOne", "PickMultiple", "OpenEnded", "Secret"], "description": "Input type"},
                    "scope_warning": {
                        "type": "object",
                        "description": "Scope risk warning: {level, reason, recommendation}",
                    },
                },
                "required": ["question", "options"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "respond_to_user",
            "description": "Send final response AFTER completing all actions. Include follow-up options. Never use just to ask what to do.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Formatted response (supports markdown)"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "value": {"type": "string"},
                                "description": {"type": "string"},
                                "icon": {"type": "string"},
                            },
                        },
                        "description": "Follow-up action buttons (2+ options)",
                    },
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "present_billing_offer",
            "description": "Show billing/upgrade offer when low on credits or plan-limited.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Why: low_credits, plan_limit, feature_gated"},
                    "current_plan": {"type": "string"},
                    "recommended_plan": {"type": "string"},
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_interface_editor",
            "description": "Launch React app builder on an agent's SQLite database. Agent = backend, interface = product. Suggest after build success + trigger configured.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Agent to build interface for"},
                },
                "required": ["agent_name"],
            },
        },
    },

    # ═══════════════════════════════════════════════════════════
    # 4. UTILITY — Memory, credits, time, workspace, SMTP, files
    # ═══════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "get_user_memory",
            "description": "Recall persistent user facts: role, company, preferences. Call at session start.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query to filter memories"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_user_memory",
            "description": "Store a new user fact. Call immediately when learning new facts (Twin brainstorm rule).",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Fact to store"},
                    "metadata": {"type": "object", "description": "{type: preference|role|company|decision}"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_credits_info",
            "description": "Check user credit balance and billing plan. Call before answering cost questions (Twin review rule).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get current UTC timestamp for scheduling decisions.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_workspace_name",
            "description": "Name/rename the workspace. Call proactively when creating first agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Workspace name"},
                    "icon": {"type": "string", "description": "Emoji icon"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "configure_smtp",
            "description": "Set up custom SMTP. Collect ALL fields via present_options with Secret for password FIRST. NEVER include password in goal text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "SMTP hostname"},
                    "port": {"type": "integer", "description": "587 TLS / 465 SSL"},
                    "username": {"type": "string"},
                    "password": {"type": "string", "description": "Collected via Secret type"},
                    "from_email": {"type": "string"},
                    "from_name": {"type": "string"},
                    "use_tls": {"type": "boolean", "description": "Default: true"},
                },
                "required": ["host", "port", "username", "password", "from_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_smtp",
            "description": "Remove custom SMTP, revert to default.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_operation",
            "description": "File operations: read, write, download_via_curl, upload_via_curl, extract_zip, list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["read", "write", "download_via_curl", "upload_via_curl", "extract_zip", "list"]},
                    "filename": {"type": "string", "description": "Bare filename (no paths)"},
                    "content": {"type": "string", "description": "For write action"},
                    "url": {"type": "string", "description": "For download/upload"},
                    "curl_args": {"type": "string", "description": "Extra curl flags"},
                    "encoding": {"type": "string", "enum": ["text", "base64"]},
                    "offset_chars": {"type": "integer", "description": "Read paging offset"},
                    "max_chars": {"type": "integer", "description": "Read max chars"},
                },
                "required": ["action"],
            },
        },
    },

    # ═══════════════════════════════════════════════════════════
    # 5. SELF-EXTENSION — Dynamic tool building
    # ═══════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "auto_build_tool",
            "description": "Dynamically create a new platform tool. Describe what it does; it gets built, safety-scanned, and registered.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "description": "snake_case name"},
                    "description": {"type": "string", "description": "What the tool does"},
                    "input_schema": {"type": "object", "description": "JSON schema for inputs"},
                    "implementation_hint": {"type": "string", "description": "Implementation hint"},
                },
                "required": ["tool_name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_tool_exists",
            "description": "Check if a tool exists on the platform.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string"},
                },
                "required": ["tool_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_built_tool",
            "description": "Execute a dynamically-built tool by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string"},
                    "inputs": {"type": "object", "description": "Tool input parameters"},
                },
                "required": ["tool_name"],
            },
        },
    },

    # ═══════════════════════════════════════════════════════════
    # 6. HEALTH — Proactive monitoring
    # ═══════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "health_check_agents",
            "description": "Scan all agents for health issues: consecutive failures, stuck sessions, depleted budgets. Returns issues + auto-fix recommendations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "auto_fix": {"type": "boolean", "description": "Auto-apply fixes. Default: false"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_agent_sessions",
            "description": "Get recent execution sessions for an agent: status, loop count, tokens, errors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string"},
                },
                "required": ["agent_name"],
            },
        },
    },
]
