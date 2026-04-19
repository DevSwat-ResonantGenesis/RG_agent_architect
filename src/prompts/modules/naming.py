"""Naming conventions — workspace and agent naming."""

ID = "naming"
TAGS = ["build", "control"]
ALWAYS = False

PROMPT = """<naming>
When creating the first agent, check if workspace has default name ("New workspace"). If so, call set_workspace_name(name, icon) in the same turn as build_agent.
Workspace names = broad domain ("Sales & Prospection", "Content & Marketing").
Agent names = specific task ("Morning Briefing", "Lead Enrichment").
</naming>"""
