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
]
