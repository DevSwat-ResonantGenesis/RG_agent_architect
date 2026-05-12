"""Agent Recipes — Proven configurations the architect draws from.

Each recipe encodes domain expertise: which tools work, what model/temperature
is optimal, what loop budget is needed, and what pitfalls to avoid.

The architect's planning LLM call gets the matching recipe injected as context
so it makes EXPERT decisions instead of guessing from a bare JSON template.
"""
from typing import Dict, List, Optional

RECIPES: Dict[str, Dict] = {

    "researcher": {
        "keywords": ["research", "find out", "investigate", "analyze", "study", "report on", "learn about", "deep dive"],
        "tools": ["web_search", "fetch_url", "news_search", "memory_write", "memory_read"],
        "model": "groq/llama-3.3-70b-versatile",
        "temperature": 0.4,
        "max_loops": 25,
        "description": "Gathers information from multiple sources, cross-references, and produces structured analyses.",
        "tool_reasoning": {
            "web_search": "Broad discovery of relevant sources and data",
            "fetch_url": "Read full articles/pages for detailed extraction",
            "news_search": "Latest developments and breaking information",
            "memory_write": "Store findings between loops to avoid re-reading",
            "memory_read": "Recall stored findings for synthesis",
        },
        "pitfalls": [
            "Without memory_write, agent re-reads same sources in later loops",
            "Too few loops (<15) means shallow research — only top results",
            "Temperature >0.6 causes hallucinated citations",
        ],
    },

    "scraper": {
        "keywords": ["scrape", "extract data", "pull data from", "harvest", "crawl", "collect from website"],
        "tools": ["web_search", "fetch_url", "scrape_page", "memory_write", "memory_read"],
        "model": "groq/llama-3.3-70b-versatile",
        "temperature": 0.3,
        "max_loops": 35,
        "description": "Extracts structured data from websites systematically.",
        "tool_reasoning": {
            "web_search": "Discover target URLs and site structure",
            "fetch_url": "Read page structure before scraping",
            "scrape_page": "Extract structured data from each page",
            "memory_write": "Track scraped URLs, store extracted data",
            "memory_read": "Check what's already scraped to avoid duplicates",
        },
        "pitfalls": [
            "Scraping without memory_write causes duplicate data",
            "Need fetch_url first to understand page structure before scrape_page",
            "High temperature causes inconsistent data extraction",
            "Always check robots.txt compliance",
        ],
    },

    "monitor": {
        "keywords": ["monitor", "watch", "track", "alert", "notify", "detect changes", "keep eye on", "daily check"],
        "tools": ["web_search", "fetch_url", "send_email", "memory_write", "memory_read"],
        "model": "groq/llama-3.3-70b-versatile",
        "temperature": 0.3,
        "max_loops": 20,
        "description": "Periodically checks sources and alerts on changes or conditions.",
        "tool_reasoning": {
            "web_search": "Find current state of monitored topic",
            "fetch_url": "Read specific monitored pages",
            "send_email": "Send alert notifications when conditions met",
            "memory_write": "Store last known state for comparison",
            "memory_read": "Retrieve last known state to detect changes",
        },
        "pitfalls": [
            "Without memory_read/write, agent can't detect CHANGES (no baseline)",
            "Must compare current vs stored state — not just report current",
            "send_email requires SMTP configuration",
            "Best paired with a schedule (daily/hourly)",
        ],
    },

    "news_agent": {
        "keywords": ["news", "headlines", "daily digest", "briefing", "what's happening", "latest"],
        "tools": ["web_search", "fetch_url", "news_search", "memory_write"],
        "model": "groq/llama-3.3-70b-versatile",
        "temperature": 0.4,
        "max_loops": 20,
        "description": "Curates news from multiple sources into a structured digest.",
        "tool_reasoning": {
            "web_search": "Broad topic coverage across multiple sources",
            "fetch_url": "Read full articles for summaries",
            "news_search": "Latest breaking news and recent developments",
            "memory_write": "Store digest for comparison next run",
        },
        "pitfalls": [
            "Without news_search, agent misses recent events (web_search favors older content)",
            "Needs 15+ loops to cover multiple topics adequately",
            "Should store articles in memory to avoid re-summarizing same stories",
        ],
    },

    "sales_outreach": {
        "keywords": ["sales", "outreach", "lead", "prospect", "cold email", "pipeline", "generate leads"],
        "tools": ["web_search", "fetch_url", "scrape_page", "send_email", "google_sheets", "memory_write"],
        "model": "groq/llama-3.3-70b-versatile",
        "temperature": 0.6,
        "max_loops": 30,
        "description": "Researches prospects, generates personalized outreach, tracks in spreadsheet.",
        "tool_reasoning": {
            "web_search": "Research companies and decision-makers",
            "fetch_url": "Read company pages for personalization context",
            "scrape_page": "Extract contact info and company details",
            "send_email": "Send personalized outreach emails",
            "google_sheets": "Track prospects and outreach status",
            "memory_write": "Store prospect research for follow-ups",
        },
        "pitfalls": [
            "send_email requires SMTP setup",
            "google_sheets requires OAuth connection",
            "Temperature too low (<0.4) produces generic, ineffective emails",
            "Must research BEFORE emailing — never send blind outreach",
        ],
    },

    "content_creator": {
        "keywords": ["write", "blog", "article", "content", "post", "copywriting", "social media post"],
        "tools": ["web_search", "fetch_url", "memory_write", "generate_media"],
        "model": "groq/llama-3.3-70b-versatile",
        "temperature": 0.7,
        "max_loops": 20,
        "description": "Creates original content based on research and topic analysis.",
        "tool_reasoning": {
            "web_search": "Research topic, find inspiration and data points",
            "fetch_url": "Read reference articles for depth",
            "memory_write": "Store research and draft sections",
            "generate_media": "Create images/visuals for content",
        },
        "pitfalls": [
            "Temperature <0.5 produces generic, uninspired content",
            "Needs web_search for factual grounding — prevents hallucination",
            "Without memory_write, long articles lose coherence between loops",
        ],
    },

    "data_analyst": {
        "keywords": ["analyze data", "chart", "visualize", "spreadsheet", "compare", "statistics", "metrics"],
        "tools": ["web_search", "fetch_url", "scrape_page", "build_chart", "google_sheets", "memory_write"],
        "model": "openai/gpt-4o",
        "temperature": 0.3,
        "max_loops": 25,
        "description": "Collects, processes, and visualizes data with charts and analysis.",
        "tool_reasoning": {
            "web_search": "Find data sources",
            "fetch_url": "Read data pages and APIs",
            "scrape_page": "Extract structured data from tables",
            "build_chart": "Create visualizations of findings",
            "google_sheets": "Store and organize data",
            "memory_write": "Track data collection progress",
        },
        "pitfalls": [
            "Use GPT-4o for data analysis — better at structured reasoning",
            "Low temperature critical for accurate data handling",
            "google_sheets requires OAuth",
        ],
    },

    "email_automation": {
        "keywords": ["email", "send email", "email campaign", "newsletter", "email automation", "respond to email"],
        "tools": ["web_search", "fetch_url", "send_email", "configure_smtp", "memory_write", "memory_read"],
        "model": "groq/llama-3.3-70b-versatile",
        "temperature": 0.5,
        "max_loops": 20,
        "description": "Automates email workflows: research, compose, send, track.",
        "tool_reasoning": {
            "web_search": "Research context for email content",
            "fetch_url": "Read reference material",
            "send_email": "Send emails",
            "configure_smtp": "Set up email sending credentials",
            "memory_write": "Track sent emails and responses",
            "memory_read": "Check what was already sent",
        },
        "pitfalls": [
            "MUST have SMTP configured — use configure_smtp or check settings first",
            "Always test with one email before bulk sending",
            "Track sent emails in memory to avoid duplicates",
        ],
    },

    "stock_market": {
        "keywords": ["stock", "market", "trading", "price", "investment", "portfolio", "financial"],
        "tools": ["web_search", "fetch_url", "stock_market_data", "news_search", "build_chart", "memory_write"],
        "model": "groq/llama-3.3-70b-versatile",
        "temperature": 0.3,
        "max_loops": 20,
        "description": "Tracks market data, analyzes trends, generates financial reports.",
        "tool_reasoning": {
            "web_search": "Market news and analysis",
            "fetch_url": "Read financial reports and articles",
            "stock_market_data": "Real-time and historical market data",
            "news_search": "Breaking market news",
            "build_chart": "Visualize price trends and comparisons",
            "memory_write": "Store analysis for trend tracking",
        },
        "pitfalls": [
            "stock_market_data requires Alpha Vantage API key",
            "Low temperature essential — no hallucinated numbers",
            "Always cite data sources for financial claims",
        ],
    },

    "general": {
        "keywords": [],
        "tools": ["web_search", "fetch_url", "memory_write"],
        "model": "groq/llama-3.3-70b-versatile",
        "temperature": 0.5,
        "max_loops": 25,
        "description": "General-purpose agent for tasks that don't match a specific pattern.",
        "tool_reasoning": {
            "web_search": "General information gathering",
            "fetch_url": "Read web pages for details",
            "memory_write": "Store findings and progress",
        },
        "pitfalls": [
            "Consider adding more specific tools based on the actual goal",
            "If task involves output delivery, add send_email or google_sheets",
        ],
    },
}


def match_recipe(user_message: str) -> Dict:
    """Find the best matching recipe for a user's request."""
    msg_lower = user_message.lower()
    best_match = None
    best_score = 0

    for recipe_id, recipe in RECIPES.items():
        if recipe_id == "general":
            continue
        score = sum(1 for kw in recipe["keywords"] if kw in msg_lower)
        if score > best_score:
            best_score = score
            best_match = recipe_id

    if best_match and best_score > 0:
        return {"recipe_id": best_match, **RECIPES[best_match]}
    return {"recipe_id": "general", **RECIPES["general"]}


def get_recipe_context(user_message: str) -> str:
    """Generate a context block for the planning LLM with expert knowledge."""
    recipe = match_recipe(user_message)
    rid = recipe["recipe_id"]

    lines = [
        f"EXPERT RECOMMENDATION (based on proven {rid} configurations):",
        f"  Recommended tools: {', '.join(recipe['tools'])}",
    ]
    for tool, reason in recipe.get("tool_reasoning", {}).items():
        lines.append(f"    - {tool}: {reason}")
    lines.append(f"  Recommended model: {recipe['model']}")
    lines.append(f"  Recommended temperature: {recipe['temperature']}")
    lines.append(f"  Recommended max_loops: {recipe['max_loops']}")
    lines.append(f"  Agent type: {recipe['description']}")
    if recipe.get("pitfalls"):
        lines.append("  Known pitfalls to AVOID:")
        for p in recipe["pitfalls"]:
            lines.append(f"    ⚠ {p}")
    return "\n".join(lines)
