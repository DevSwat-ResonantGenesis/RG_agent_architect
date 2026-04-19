"""Goal crafting — how to write good agent goals. Injected for build intents."""

ID = "goal_crafting"
TAGS = ["build", "control", "brainstorm"]
ALWAYS = False

PROMPT = """<goal_crafting>
A good goal is: outcome-oriented, concise (2-3 sentences), specific about services, clear about where output goes.

IMPORTANT: The goal must describe WHAT the agent does in a single execution, NOT how often it runs. Strip all recurrence language ("every day", "daily", "weekly"). Handle scheduling via set_trigger after build.

CRITICAL: Never include passwords, API keys, or secrets in the goal text.

Bad: "Keep me updated on tech news"
Good: "Collect the top 10 HackerNews stories and trending GitHub repos in AI/ML, send a briefing email with summaries and links."

Bad: "Help me with sales"
Good: "Check HubSpot pipeline for deals with no activity in 3+ days, draft personalized follow-up emails, send via Gmail."

When goal is ready, check scope_risk BEFORE presenting. Then show in blockquote and confirm with present_options: ["Build it", "Let me adjust something"].
</goal_crafting>"""
