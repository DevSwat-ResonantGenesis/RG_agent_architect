"""Platform architecture — workspaces, agents, runs. Always injected."""

ID = "platform"
TAGS = ["base"]
ALWAYS = True

PROMPT = """<system>
Three layers: workspaces, agents, and runs.

Workspace — A domain grouping (e.g. "Sales & Prospection"). Multiple agents per workspace.
Agent — A reusable autonomous workflow: goal, instructions, tools, triggers, persistent state.
Run — A single execution. Outcome: SUCCESS, PARTIAL, FAIL.

Builder vs Runner:
Builder = high-reasoning model (gpt-4o, claude-3-5-sonnet). Creates/updates agents, discovers APIs, creates tools. Expensive — runs once per creation.
Runner = smaller model (groq/llama-3.3-70b). Executes existing agents using pre-built tools. If it hits a gap, finishes PARTIAL.
</system>"""
