"""
RG Agent Architect — Tool Definitions for ReAct Agent Loop

These are the function schemas the LLM can call during orchestration.
Instead of regex routing, the LLM decides which tool to call based on
the user's message and conversation context.
"""

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_agents",
            "description": "List all agents in the user's workspace. Shows name, model, tools, status for each agent. Use this when the user asks about their agents, wants a workspace overview, or you need to find an agent by name before operating on it.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_agent_details",
            "description": "Get detailed info about a specific agent including recent run sessions, status, tools, and configuration. Use this to check agent health, diagnose issues, or review before modifying.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent to inspect",
                    },
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_agent",
            "description": "Permanently delete an agent from the workspace. Use when the user asks to delete, remove, or destroy an agent. Act immediately — do not ask for confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent to delete",
                    },
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_agent",
            "description": "Create a new agent with full configuration. You MUST provide a detailed system_prompt with step-by-step INSTRUCTIONS — this is what makes agents work. After creating, ALWAYS call run_agent immediately. Never create without running.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Descriptive agent name",
                    },
                    "description": {
                        "type": "string",
                        "description": "Clear 1-sentence purpose",
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "CRITICAL: Detailed step-by-step instructions for the agent. Must include: role definition, numbered steps with specific tool names and queries, expected output format, where to store results, and constraints. This is the agent's playbook — without it, the agent will wander aimlessly.",
                    },
                    "goal": {
                        "type": "string",
                        "description": "Specific, measurable, outcome-oriented goal in 2-3 sentences",
                    },
                    "provider": {
                        "type": "string",
                        "enum": ["groq", "openai", "anthropic", "google"],
                        "description": "LLM provider. Default: groq",
                    },
                    "model": {
                        "type": "string",
                        "description": "Model name. Default: llama-3.3-70b-versatile",
                    },
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of platform tool names this agent can use",
                    },
                    "temperature": {
                        "type": "number",
                        "description": "LLM temperature. Default: 0.6",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["governed", "supervised", "unbounded"],
                        "description": "Autonomy mode. Default: governed",
                    },
                    "max_loops": {
                        "type": "integer",
                        "description": "Maximum execution iterations. Default: 25. Set 30-50 for complex multi-step tasks, 15-20 for simple tasks. NEVER use default for complex work.",
                    },
                    "budget": {
                        "type": "object",
                        "properties": {
                            "max_tokens_per_run": {
                                "type": "integer",
                                "description": "Max tokens per single run. Default: 50000",
                            },
                            "max_runs_per_day": {
                                "type": "integer",
                                "description": "Max runs allowed per day. Default: 10",
                            },
                            "initial_credits": {
                                "type": "number",
                                "description": "Initial credit allocation. Default: 100.0",
                            },
                        },
                        "description": "Budget limits for the agent. Smart defaults applied if omitted.",
                    },
                },
                "required": ["name", "description", "system_prompt", "goal", "tools"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_agent",
            "description": "Execute an existing agent immediately. ALWAYS call this right after create_agent — never leave an agent unrun. Returns the execution result or status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent to run",
                    },
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify_agent",
            "description": "Update an existing agent's configuration — change tools, model, goal, description, system prompt, or other settings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent to modify",
                    },
                    "changes": {
                        "type": "object",
                        "description": "Key-value pairs of fields to update. Valid keys: name, description, system_prompt, provider, model, temperature, max_tokens, tools, mode, is_active, max_loops (1-100, controls how many iterations the agent can run before stopping), safety_config (JSON with max_loops, allowed_actions, etc.), tool_mode, autonomous",
                    },
                },
                "required": ["agent_name", "changes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_agent",
            "description": "Set up automated recurring runs for an agent. Specify interval in seconds or cron expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent to schedule",
                    },
                    "interval_seconds": {
                        "type": "integer",
                        "description": "Run interval in seconds. Common: 3600=hourly, 86400=daily, 604800=weekly",
                    },
                    "cron_expression": {
                        "type": "string",
                        "description": "Cron expression for schedule. Alternative to interval_seconds.",
                    },
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_agent",
            "description": "Deactivate an agent — stops it from running. Does not delete it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent to stop/deactivate",
                    },
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_agent_sessions",
            "description": "Get recent execution sessions for an agent — shows status (completed/failed/running), loop count, tokens used, errors, and goals. Use this to diagnose why an agent failed, check if it's running, or review past performance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent to check sessions for",
                    },
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_platform_tools",
            "description": "List all available platform tools that agents can use. Returns tool names organized by category (search, memory, code, media, integrations, etc.). Use when the user asks what tools are available or when you need to recommend tools for an agent.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_agent_budget",
            "description": "Set or update budget limits for an agent — max tokens per run, max runs per day, credit allocation. Use when user wants to control agent spending.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent to set budget for",
                    },
                    "max_tokens_per_run": {
                        "type": "integer",
                        "description": "Max tokens per single run",
                    },
                    "max_runs_per_day": {
                        "type": "integer",
                        "description": "Max runs allowed per day",
                    },
                    "credits": {
                        "type": "number",
                        "description": "Credits to allocate to the agent's wallet",
                    },
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_agent_wallet",
            "description": "Check an agent's wallet balance and spending history. Use to review costs or diagnose budget issues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent to check wallet for",
                    },
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "auto_build_tool",
            "description": "Dynamically create a new platform tool at runtime. Describe what the tool should do and it will be built, safety-scanned, and registered. Use when no existing tool covers the need.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Snake_case name for the new tool",
                    },
                    "description": {
                        "type": "string",
                        "description": "What the tool does — clear, specific",
                    },
                    "input_schema": {
                        "type": "object",
                        "description": "JSON schema for tool input parameters",
                    },
                    "implementation_hint": {
                        "type": "string",
                        "description": "Hint for how to implement (e.g. API endpoint, logic)",
                    },
                },
                "required": ["tool_name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_tool_exists",
            "description": "Check if a tool with a given name exists on the platform. Returns the tool if found, or suggests building it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Name of the tool to check",
                    },
                },
                "required": ["tool_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_built_tool",
            "description": "Execute a dynamically-built tool by name with given inputs. Use for tools created via auto_build_tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Name of the built tool to execute",
                    },
                    "inputs": {
                        "type": "object",
                        "description": "Input parameters for the tool",
                    },
                },
                "required": ["tool_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "health_check_agents",
            "description": "Run a health check across all agents — detect consecutive failures, stuck sessions, depleted budgets. Returns issues found and auto-fix recommendations. Use proactively or when diagnosing problems.",
            "parameters": {
                "type": "object",
                "properties": {
                    "auto_fix": {
                        "type": "boolean",
                        "description": "If true, automatically apply recommended fixes. Default: false",
                    },
                },
                "required": [],
            },
        },
    },
    # ── NEW TOOLS: Twin-level orchestrator capabilities ──
    {
        "type": "function",
        "function": {
            "name": "workspace_snapshot",
            "description": "Get a complete workspace overview in one call: all agents with status, available platform tools, and user memory facts. Use this at the START of every session to understand the user's current state before taking any action.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agent_snapshot",
            "description": "Deep inspect a specific agent: full config, system_prompt/instructions, recent run history with outcomes, tools assigned, budget status. Use to understand what an agent does before modifying or diagnosing it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent to inspect deeply",
                    },
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_snapshot",
            "description": "Get the full trace of a single agent run: every decision, tool call, result, and error. Use to diagnose why a specific run failed or to review what the agent actually did.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Session/run ID to inspect. If omitted, uses the most recent run.",
                    },
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_memory",
            "description": "Recall persistent user facts stored from previous sessions — role, company, preferences, past decisions. Use at session start or when you need context about the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional search query to filter memories. If omitted, returns general user facts.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_user_memory",
            "description": "Store a new user fact for future sessions. Use when the user shares their role, company, preferences, or any persistent context. Facts persist across all conversations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The fact to store (e.g. 'User is a SaaS founder building AI tools')",
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional metadata: {type: 'preference'|'role'|'company'|'decision'}",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "present_options",
            "description": "Show clickable choices to the user in the chat interface. Use for confirmations, scope decisions, or collecting input. This is a SEMI-TERMINAL action — after calling this, STOP the loop and wait for user response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question or prompt to show the user",
                    },
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "Button text"},
                                "value": {"type": "string", "description": "Value returned when selected"},
                                "description": {"type": "string", "description": "Optional subtitle"},
                                "icon": {"type": "string", "description": "Optional emoji icon"},
                            },
                            "required": ["label", "value"],
                        },
                        "description": "2-4 clickable option buttons",
                    },
                    "question_type": {
                        "type": "string",
                        "enum": ["PickOne", "PickMultiple", "OpenEnded", "Secret"],
                        "description": "Type of input: PickOne (radio), PickMultiple (checkboxes), OpenEnded (text), Secret (masked password)",
                    },
                    "scope_warning": {
                        "type": "object",
                        "description": "Optional scope risk warning: {level: 'high'|'moderate', reason: '...', recommendation: '...'}",
                    },
                },
                "required": ["question", "options"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_credits_info",
            "description": "Check the user's credit balance and billing plan. Use when the user asks about costs, credits, or before creating expensive agents.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current UTC timestamp. Use for scheduling decisions or time-sensitive operations.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "respond_to_user",
            "description": "Send a final response to the user. ONLY use this AFTER you have completed all actions (create + run + get results). Never use this just to ask the user what to do — act first, report results after. Include follow-up options.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The formatted response message to show the user (supports markdown)",
                    },
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
                        "description": "Follow-up action buttons for the user. Always provide at least 2 options.",
                    },
                },
                "required": ["message"],
            },
        },
    },
    # ── TWIN ARCHITECTURE TOOLS — Full parity with Twin's 21 orchestrator tools ──
    {
        "type": "function",
        "function": {
            "name": "continue_build",
            "description": "Modify or extend an existing agent by sending rebuild instructions to the builder. Use when the user wants to change what an agent does, add tools, fix issues, or improve instructions. Instructions must be a THREE-PART DELTA: what CHANGES, what STAYS, what STOPS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent to rebuild/modify",
                    },
                    "instructions": {
                        "type": "string",
                        "description": "Rebuild instructions as a 3-part delta:\n1. What CHANGES now (new behavior, tools, goal)\n2. What STAYS THE SAME (preserve existing functionality)\n3. What STOPS happening (remove old behavior)",
                    },
                },
                "required": ["agent_name", "instructions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "message_build",
            "description": "Send guidance to an agent's active build session. Use when a build is in progress and you need to provide additional context, answer the builder's question, or redirect the build. The message is queued and processed when the builder is ready.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent with active build",
                    },
                    "message": {
                        "type": "string",
                        "description": "Guidance message for the builder",
                    },
                },
                "required": ["agent_name", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_workspace_name",
            "description": "Set or rename the user's workspace. Call proactively when creating the first agent if the workspace has a default name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "New workspace name (e.g. 'Sales Ops', 'Content Machine')",
                    },
                    "icon": {
                        "type": "string",
                        "description": "Emoji icon for the workspace",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_interface_editor",
            "description": "Launch the interface editor to build a shareable React app + API on top of an agent's SQLite database. The agent becomes the backend; the interface is the product. Suggest after successful build + trigger configured.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent to build an interface for",
                    },
                },
                "required": ["agent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workspace_databases",
            "description": "List all agent SQLite databases in the workspace. Shows which agents have persistent data that can be queried. Use before query_cross_agent_database.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_cross_agent_database",
            "description": "Execute a read-only SQL query against an agent's SQLite database. SELECT only — no INSERT/UPDATE/DELETE. Use to inspect agent data, cross-reference between agents, or answer questions about what agents have collected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Name of the agent whose database to query",
                    },
                    "query": {
                        "type": "string",
                        "description": "SQL SELECT query to execute",
                    },
                },
                "required": ["agent_name", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "configure_smtp",
            "description": "Set up a custom SMTP email server for the user. Removes rate limits and Twin branding from sent emails. Collect ALL fields via present_options with Secret type for password BEFORE calling this.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "SMTP server hostname (e.g. smtp.gmail.com)",
                    },
                    "port": {
                        "type": "integer",
                        "description": "SMTP port (587 for TLS, 465 for SSL)",
                    },
                    "username": {
                        "type": "string",
                        "description": "SMTP username/email",
                    },
                    "password": {
                        "type": "string",
                        "description": "SMTP password (collected via Secret input type)",
                    },
                    "from_email": {
                        "type": "string",
                        "description": "From email address",
                    },
                    "from_name": {
                        "type": "string",
                        "description": "From display name",
                    },
                    "use_tls": {
                        "type": "boolean",
                        "description": "Use TLS encryption. Default: true",
                    },
                },
                "required": ["host", "port", "username", "password", "from_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_smtp",
            "description": "Remove custom SMTP configuration and revert to default email sending.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_operation",
            "description": "Perform file operations in the workspace: read, write, download_via_curl, upload_via_curl, extract_zip, or list files. Agents use this for data processing, report generation, and file management.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write", "download_via_curl", "upload_via_curl", "extract_zip", "list"],
                        "description": "File operation to perform",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Bare filename (no paths). Required for read/write/download/upload/extract.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write (for write action)",
                    },
                    "url": {
                        "type": "string",
                        "description": "URL for download/upload operations",
                    },
                    "curl_args": {
                        "type": "string",
                        "description": "Additional curl flags for download/upload",
                    },
                    "encoding": {
                        "type": "string",
                        "enum": ["text", "base64"],
                        "description": "Encoding for write: text (default) or base64 for binary",
                    },
                    "offset_chars": {
                        "type": "integer",
                        "description": "Character offset for paging large files (read action)",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Max characters to return (read action)",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "present_billing_offer",
            "description": "Present a billing/upgrade offer to the user when they're running low on credits or need more capacity. Shows plan comparison and upgrade options.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Why the offer is being shown (e.g. 'low_credits', 'plan_limit', 'feature_gated')",
                    },
                    "current_plan": {
                        "type": "string",
                        "description": "User's current plan",
                    },
                    "recommended_plan": {
                        "type": "string",
                        "description": "Recommended upgrade plan",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]
