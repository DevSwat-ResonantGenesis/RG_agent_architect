"""Tool Registry — 13 built-in + 35 OAuth + custom tools"""
from typing import Any, Dict, List
from src.models.tools import BUILTIN_TOOLS, OAUTH_SERVICES, ToolCategory, ToolDefinition

DESCRIPTIONS = {
    "web_search": "Perplexity AI natural language Q&A with citations",
    "scrape_page": "Firecrawl browser automation, JS rendering, markdown extraction",
    "deep_research": "100+ sources, 10-20 searches, 1-3 min comprehensive reports",
    "stock_market_data": "Alpha Vantage: quotes, 20yr historical, sentiment news",
    "send_email": "Mailgun/SMTP: HTML, attachments, CID image embed",
    "configure_smtp": "Custom email server setup",
    "delete_smtp": "Revert to Mailgun",
    "build_chart": "Chart.js bar/line/pie/radar/scatter → PNG",
    "scrape_platforms": "35+ Apify scrapers (LinkedIn, Instagram, Reddit, etc.)",
    "google_sheets": "Create/read/append/update/export spreadsheets",
    "create_presentation": "AI 1-60 slide decks → PDF",
    "documents": "Google Docs CRUD",
    "generate_media": "AI image (sync) + video (async) generation",
}


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        for name in BUILTIN_TOOLS:
            self._tools[name] = ToolDefinition(name=name, description=DESCRIPTIONS.get(name,""), category=ToolCategory.BUILTIN)
        for svc in OAUTH_SERVICES:
            self._tools[f"oauth_{svc}"] = ToolDefinition(name=f"oauth_{svc}", description=f"OAuth: {svc}", category=ToolCategory.OAUTH, oauth_service=svc)

    def register_custom_tool(self, tool: ToolDefinition):
        self._tools[tool.name] = tool

    async def list_all_tools(self) -> List[Dict[str, Any]]:
        return [{"name": t.name, "description": t.description, "category": t.category.value} for t in self._tools.values()]

    def tool_exists(self, name: str) -> bool:
        return name in self._tools
