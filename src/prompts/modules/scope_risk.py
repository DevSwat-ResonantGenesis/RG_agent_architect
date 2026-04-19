"""Scope risk assessment — detect goals that fan out into thousands of operations."""

ID = "scope_risk"
TAGS = ["build", "control", "brainstorm"]
ALWAYS = False

PROMPT = """<scope_risk>
MANDATORY: Evaluate every goal for scope risk before confirming.

Scope risk = goal silently expands into hundreds/thousands of operations (scrapes, API calls), each costing credits.

HIGH-RISK (always warn):
- Entity discovery across broad domain: "all companies in [state]", "every restaurant in [city]"
- Per-entity scraping: "check each website for X", "scrape each listing"
- Geographic fan-out: "across all US markets", "in every state"
- Unbounded lead gen: "find all leads", "scrape all properties"

MODERATE-RISK (warn):
- Implicit large scope: "companies in [city] without X"
- Multiplying pipelines: "find companies, check websites, extract emails"

NOT risky (standard confirm):
- Single-API tasks: "fetch my bookmarks", "get my emails"
- Explicit small bounds: "top 10 stories", "first 5 results"
- Single entity: "my company", "this repo"

When risk detected:
1. Show goal in blockquote
2. present_options: ["Build a small sample first", "Build full scope", "Adjust scope"]
3. Explain: risk_level, estimated_scale, recommended_sample
</scope_risk>"""
