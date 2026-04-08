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
    _t("workspace_snapshot", "Get list of all agents, counts, workspace state", {}, []),
    _t("list_workspace_tools", "List all available tools the user can assign to agents", {}, []),
    _t("get_user_memory", "Retrieve stored user preferences and facts", {}, []),
    _t("update_user_memory", "Store a user preference or fact",
       {"content": {"type": "string", "description": "Fact to remember"}}, ["content"]),
    _t("agent_snapshot", "Get agent details and recent runs",
       {"agent_id": {"type": "string"}}, ["agent_id"]),
    _t("run_snapshot", "Get details of a specific run",
       {"run_id": {"type": "string"}}, ["run_id"]),
    _t("build_agent", "Create a new autonomous agent",
       {"name": {"type": "string", "description": "Agent name"},
        "goal": {"type": "string", "description": "What the agent should do"},
        "icon": {"type": "string", "description": "Emoji icon", "default": "🤖"},
        "tools": {"type": "array", "items": {"type": "string"}, "description": "Tool names to assign"},
        "max_loops": {"type": "integer", "default": 30},
        "temperature": {"type": "number", "default": 0.5}}, ["name", "goal"]),
    _t("continue_build", "Update agent instructions",
       {"agent_id": {"type": "string"}, "instructions": {"type": "string"}}, ["agent_id", "instructions"]),
    _t("message_build", "Refine agent via natural language",
       {"agent_id": {"type": "string"}, "message": {"type": "string"}}, ["agent_id", "message"]),
    _t("run_agent", "Execute an agent now",
       {"agent_id": {"type": "string"}, "goal": {"type": "string", "description": "Optional goal override"}}, ["agent_id"]),
    _t("stop_run", "Stop an active run",
       {"run_id": {"type": "string"}}, ["run_id"]),
    _t("delete_agent", "Permanently delete an agent",
       {"agent_id": {"type": "string"}}, ["agent_id"]),
    _t("set_trigger", "Schedule agent to run on interval",
       {"agent_id": {"type": "string"}, "interval": {"type": "string", "enum": ["minutely","hourly","daily","weekly"]},
        "timezone": {"type": "string", "default": "UTC"}}, ["agent_id", "interval"]),
    _t("set_workspace_name", "Rename workspace",
       {"name": {"type": "string"}, "icon": {"type": "string"}}, ["name"]),
    _t("present_options", "Show user a choice",
       {"question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
        "question_type": {"type": "string", "enum": ["PickOne","PickMany","Confirm"]}}, ["question", "options"]),
    _t("file", "File operation",
       {"action": {"type": "string", "enum": ["read","write","download","upload","extract","list"]},
        "path": {"type": "string"}, "content": {"type": "string"}}, ["action"]),
    _t("get_current_time", "Get current UTC time", {}, []),
    _t("list_workspace_databases", "List per-agent databases", {}, []),
    _t("get_credits_info", "Get billing credits info", {}, []),
]
