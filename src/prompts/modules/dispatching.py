"""Dispatching — how to route user actions to the right tool calls."""

ID = "dispatching"
TAGS = ["control"]
ALWAYS = False

PROMPT = """<dispatching>
Create -> build_agent(name, goal, icon, tools, max_loops, model, temperature)
  ALWAYS include tools, max_loops, model. Confirm with present_options first.
  Config checklist:
  1. TOOLS — Pick from synergies. NEVER use defaults if task needs specific tools.
  2. MODEL — Simple=groq/llama-3.3-70b. Complex=openai/gpt-4o. Code=anthropic/claude-3-5-sonnet.
  3. MAX_LOOPS — web_search=1-2, fetch_url=1, scrape=2-3 loops each. 10 pages = 30+ loops.
  4. TEMPERATURE — Research=0.3-0.5, Creative=0.7-0.8.

Extend -> continue_build(agent_id, instructions)
  Phrase explicitly: what changes, what stays, what stops.

Run -> run_agent(agent_id)
  Must have instructions. If PARTIAL, use continue_build first.

Guide -> message_build(agent_id, message)
  Guidance to builder run in progress.

When unclear which agent, show list and ask with present_options.
</dispatching>"""
