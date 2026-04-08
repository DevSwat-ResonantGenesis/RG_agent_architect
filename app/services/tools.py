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
            "description": "Create a new agent with full configuration. Use after crafting a goal and determining the right tools/model. Provide all fields for a production-ready agent.",
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
                        "description": "System prompt defining the agent's role and behavior",
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
                },
                "required": ["name", "description", "goal", "tools"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_agent",
            "description": "Execute an existing agent immediately. Starts a run and returns the result or status.",
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
            "name": "respond_to_user",
            "description": "Send a final response to the user. Use this when you have gathered all needed information and want to present your answer, plan preview, brainstorm ideas, or status report. Include present_options for follow-up actions.",
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
