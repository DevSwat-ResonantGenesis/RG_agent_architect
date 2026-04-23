"""Tool Models — 13 built-in + 35 OAuth + custom API tools"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ToolCategory(str, Enum):
    BUILTIN = "builtin"
    OAUTH = "oauth"
    CUSTOM = "custom"
    SCRAPER = "scraper"


@dataclass
class ToolDefinition:
    name: str
    description: str
    category: ToolCategory
    parameters: Dict[str, Any] = field(default_factory=dict)
    oauth_service: Optional[str] = None
    scopes: List[str] = field(default_factory=list)


BUILTIN_TOOLS = [
    "web_search", "scrape_page", "deep_research", "stock_market_data",
    "send_email", "configure_smtp", "delete_smtp", "build_chart",
    "scrape_platforms", "google_sheets", "create_presentation",
    "documents", "generate_media",
]

OAUTH_SERVICES = [
    "airtable", "asana", "atlassian", "attio", "calendly", "clickup",
    "discord", "dribbble", "dropbox", "figma", "github", "gitlab",
    "gmail", "google_calendar", "google_docs", "google_drive", "hubspot",
    "linear", "linkedin", "mailchimp", "microsoft", "miro", "monday",
    "notion", "pipedrive", "salesforce", "slack", "typeform", "x_twitter",
    "xero", "youtube", "zoho_crm", "zoom",
]

def _t(name, desc, props=None, required=None):
    schema = {"type": "object", "properties": props or {}, "required": required or []}
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": schema}}

ORCHESTRATOR_TOOLS = [
    _t("workspace_snapshot", "Get all agents and workspace state"),
    _t("list_workspace_tools", "List available tools for agents"),
    _t("get_user_memory", "Get stored user preferences"),
    _t("update_user_memory", "Store a user fact",
       {"content": {"type": "string"}}, ["content"]),
    _t("agent_snapshot", "Get agent details and recent runs",
       {"agent_id": {"type": "string"}}, ["agent_id"]),
    _t("run_snapshot", "Get run details",
       {"run_id": {"type": "string"}}, ["run_id"]),
    _t("build_agent", "Create a new autonomous agent with proper configuration",
       {"name": {"type": "string", "description": "Agent name"},
        "goal": {"type": "string", "description": "What the agent should do — outcome-oriented, no recurrence language"},
        "icon": {"type": "string", "description": "Emoji icon"},
        "tools": {"type": "array", "items": {"type": "string"}, "description": "List of tools the agent needs (e.g. web_search, fetch_url, scrape_page, memory_write)"},
        "max_loops": {"type": "integer", "description": "Max execution loops — estimate based on task complexity (20-50)"},
        "model": {"type": "string", "description": "LLM model (groq/llama-3.3-70b-versatile, openai/gpt-4o, anthropic/claude-3-5-sonnet-20241022)"},
        "temperature": {"type": "number", "description": "Temperature (0.3-0.8 based on creativity needed)"}}, ["name", "goal"]),
    _t("continue_build", "Update agent instructions",
       {"agent_id": {"type": "string"}, "instructions": {"type": "string"}}, ["agent_id", "instructions"]),
    _t("message_build", "Refine agent via natural language",
       {"agent_id": {"type": "string"}, "message": {"type": "string"}}, ["agent_id", "message"]),
    _t("run_agent", "Execute an agent now",
       {"agent_id": {"type": "string"}, "goal": {"type": "string", "description": "Optional goal override"}}, ["agent_id"]),
    _t("stop_run", "Stop an active run",
       {"run_id": {"type": "string"}}, ["run_id"]),
    _t("delete_agent", "Permanently delete a single agent by ID",
       {"agent_id": {"type": "string"}}, ["agent_id"]),
    _t("delete_all_agents", "Delete ALL agents in the workspace. Use when user wants to delete all/multiple agents at once."),
    _t("modify_agent", "Add or remove tools, update config on an existing agent",
       {"agent_id": {"type": "string", "description": "Agent ID to modify"},
        "add_tools": {"type": "string", "description": "Comma-separated tools to add"},
        "remove_tools": {"type": "string", "description": "Comma-separated tools to remove"},
        "max_loops": {"type": "integer", "description": "New max loops value"},
        "temperature": {"type": "number", "description": "New temperature"},
        "model": {"type": "string", "description": "New model"}}, ["agent_id"]),
    _t("set_trigger", "Schedule agent to run on interval (minutely, hourly, daily, weekly)",
       {"agent_id": {"type": "string"}, "interval": {"type": "string", "description": "One of: minutely, hourly, daily, weekly"},
        "timezone": {"type": "string"}}, ["agent_id", "interval"]),
    _t("set_workspace_name", "Rename workspace",
       {"name": {"type": "string"}, "icon": {"type": "string"}}, ["name"]),
    _t("present_options", "Show user a choice between 2-4 options",
       {"question": {"type": "string"}, "options": {"type": "string", "description": "Comma-separated list of options"}}, ["question", "options"]),
    _t("get_current_time", "Get current UTC time"),
    _t("list_workspace_databases", "List per-agent databases"),
    _t("get_credits_info", "Get user wallet, credits, plan, and economic state"),
    _t("check_credits", "Check if user has enough credits to run an agent"),
    _t("check_integrations", "Check which OAuth integrations are connected and which are missing",
       {"tools": {"type": "string", "description": "Comma-separated tool names that need integrations"}}, ["tools"]),
    _t("get_agent_settings", "Get agent-specific settings from auth service",
       {"agent_id": {"type": "string"}}, ["agent_id"]),
    _t("get_agent_chain_status", "Get agent blockchain registration and identity status",
       {"agent_id": {"type": "string"}}, ["agent_id"]),
    _t("get_agent_memory", "Get agent-specific hash sphere memory and learnings",
       {"agent_id": {"type": "string"}}, ["agent_id"]),
    _t("get_dual_memory", "Get combined user + agent hash sphere memory",
       {"agent_id": {"type": "string"}}, ["agent_id"]),
    _t("ask_memory", "Ask a question to RAG memory — agent learns from past context",
       {"question": {"type": "string"}, "agent_id": {"type": "string"}}, ["question"]),
    _t("store_insight", "Store something you learned during this conversation for future reference",
       {"insight": {"type": "string", "description": "What you learned"}, "category": {"type": "string", "description": "One of: observation, user_preference, agent_pattern, failure_pattern, success_pattern"}},
       ["insight", "category"]),
    _t("retrieve_architect_context", "Get your accumulated knowledge: past insights, user preferences, patterns you've noticed. Call this at the start of every session to remember what you know."),
    # ── Prompt Management ──
    _t("get_agent_prompt", "Read an agent's current system prompt / instructions",
       {"agent_id": {"type": "string"}}, ["agent_id"]),
    _t("update_agent_prompt", "Write or replace an agent's system prompt / instructions",
       {"agent_id": {"type": "string"}, "prompt": {"type": "string", "description": "The full new system prompt text"}},
       ["agent_id", "prompt"]),
    # ── Agent Config ──
    _t("update_agent_config", "Update agent configuration: model, temperature, max_tokens, mode, tools, provider, is_active, max_loops, tool_mode",
       {"agent_id": {"type": "string"},
        "model": {"type": "string", "description": "LLM model e.g. groq/llama-3.3-70b-versatile, openai/gpt-4o"},
        "temperature": {"type": "number"}, "max_tokens": {"type": "integer"},
        "mode": {"type": "string", "description": "Agent mode: smart, autonomous, manual"},
        "tools": {"type": "array", "items": {"type": "string"}, "description": "Replace tool list"},
        "is_active": {"type": "boolean"}, "max_loops": {"type": "integer"},
        "tool_mode": {"type": "string", "description": "smart or manual"}}, ["agent_id"]),
    # ── Schedules ──
    _t("create_schedule", "Create a cron schedule for an agent to run automatically",
       {"agent_id": {"type": "string"},
        "cron": {"type": "string", "description": "Cron expression e.g. '0 9 * * *' for daily 9am, '0 * * * *' for hourly"},
        "goal": {"type": "string", "description": "Goal override for scheduled runs"},
        "timezone": {"type": "string", "description": "Timezone e.g. UTC, America/New_York"}}, ["agent_id", "cron"]),
    # ── Session History ──
    _t("get_agent_sessions", "Get recent execution sessions/runs for an agent",
       {"agent_id": {"type": "string"}}, ["agent_id"]),
    _t("get_session_steps", "Get step-by-step execution trace for a specific session/run",
       {"session_id": {"type": "string"}}, ["session_id"]),
    # ── Agent Delegation (spawn / use any agent) ──
    _t("delegate_to_agent", "Delegate a sub-task to any existing agent by ID — agent runs and returns its result. Use this to orchestrate multi-agent workflows.",
       {"agent_id": {"type": "string", "description": "ID of the agent to delegate to"},
        "task": {"type": "string", "description": "The task/goal for the agent to execute"}}, ["agent_id", "task"]),
    _t("delegate_by_name", "Delegate a sub-task to an agent by NAME — finds the agent and runs it. Use when user says 'ask my X agent to do Y'.",
       {"agent_name": {"type": "string", "description": "Name of the agent to delegate to"},
        "task": {"type": "string", "description": "The task/goal for the agent to execute"}}, ["agent_name", "task"]),
    # ── TODO / Planning / Brainstorm ──
    _t("create_task", "Create a TODO task — persisted in workspace memory. Can be per-agent or workspace-wide.",
       {"title": {"type": "string", "description": "Task title"},
        "description": {"type": "string", "description": "Detailed description"},
        "priority": {"type": "string", "description": "One of: high, medium, low"},
        "status": {"type": "string", "description": "One of: pending, in_progress, completed, blocked"},
        "agent_id": {"type": "string", "description": "Optional — scope task to a specific agent"},
        "tags": {"type": "string", "description": "Comma-separated tags"}}, ["title"]),
    _t("list_tasks", "List TODO tasks from workspace memory. Filter by agent_id for per-agent tasks, or leave empty for all workspace tasks.",
       {"agent_id": {"type": "string", "description": "Optional — filter tasks for specific agent"},
        "query": {"type": "string", "description": "Optional search query to filter tasks"}}, []),
    _t("update_task", "Update a task's status, priority, or description.",
       {"task_id": {"type": "string", "description": "Task ID to update"},
        "status": {"type": "string", "description": "New status: pending, in_progress, completed, blocked"},
        "priority": {"type": "string", "description": "New priority: high, medium, low"},
        "title": {"type": "string", "description": "Updated title"},
        "description": {"type": "string", "description": "Updated description"},
        "agent_id": {"type": "string", "description": "Agent scope"}}, ["task_id"]),
    _t("brainstorm", "Store a brainstorm idea or plan — persisted in workspace memory. Can be per-agent or general.",
       {"content": {"type": "string", "description": "The brainstorm idea, plan, or thought"},
        "agent_id": {"type": "string", "description": "Optional — scope to a specific agent"}}, ["content"]),
    _t("get_workspace_plan", "Get the full workspace plan: all TODO tasks + brainstorms across all agents. Use this to review the current state of planning."),
    # ── Session Control (cancel, approve, emergency stop) ──
    _t("cancel_session", "Cancel/stop a running agent session immediately.",
       {"session_id": {"type": "string", "description": "Session ID to cancel"}}, ["session_id"]),
    _t("emergency_stop", "EMERGENCY KILL SWITCH — cancel ALL running sessions and disable ALL schedules for an agent. Use when agent is out of control.",
       {"agent_id": {"type": "string", "description": "Agent ID to emergency stop"}}, ["agent_id"]),
    _t("approve_step", "Approve a pending step that requires human approval.",
       {"session_id": {"type": "string", "description": "Session ID"},
        "step_id": {"type": "string", "description": "Step ID to approve"}}, ["session_id", "step_id"]),
    _t("get_pending_approvals", "List all pending approval requests across all agents."),
    # ── Full Tool Registry (74+ tools from Agent Engine) ──
    _t("list_engine_tools", "List ALL platform tools from Agent Engine (74+ tools). Use this to see every tool available for agents."),
    _t("execute_tool", "Execute any platform tool directly for testing. Verify a tool works before assigning it to an agent.",
       {"tool_name": {"type": "string", "description": "Tool name (e.g. web_search, fetch_url)"},
        "tool_input": {"type": "object", "description": "Input parameters for the tool"}}, ["tool_name", "tool_input"]),
    # ── Provider & Metrics ──
    _t("list_providers", "List all available LLM providers and models. Check which are healthy before selecting a model."),
    _t("get_agent_metrics", "Get performance metrics for an agent: sessions, success rate, avg duration.",
       {"agent_id": {"type": "string"}}, ["agent_id"]),
    # ── Schedule Management ──
    _t("list_schedules", "List all cron schedules for an agent.",
       {"agent_id": {"type": "string"}}, ["agent_id"]),
]
