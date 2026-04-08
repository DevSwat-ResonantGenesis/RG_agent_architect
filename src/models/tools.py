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

ORCHESTRATOR_TOOLS = [
    "workspace_snapshot", "list_workspace_tools", "get_user_memory",
    "update_user_memory", "agent_snapshot", "run_snapshot",
    "build_agent", "continue_build", "message_build",
    "run_agent", "stop_run", "delete_agent", "set_trigger",
    "set_workspace_name", "open_interface_editor", "present_options",
    "file", "get_current_time", "configure_smtp",
    "list_workspace_databases", "get_credits_info",
]
