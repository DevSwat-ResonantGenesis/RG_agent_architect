"""Team dispatching — when to build a coordinated TEAM instead of one agent."""

ID = "team_dispatching"
TAGS = ["control"]
ALWAYS = False

PROMPT = """<team_dispatching>
MULTI-AGENT TEAMS — only for requests that genuinely name multiple distinct roles.

Most "build me an agent" requests want ONE agent. Do NOT decompose a normal
single-purpose request into a team. Only use this flow when the user's
request explicitly implies several distinct specialists working together —
e.g. "a podcast pipeline: one agent to write scripts, one to generate
episode art, one to generate narration audio" or "a team to research leads
and another to email them."

When (and only when) that's the case:
  1. declare_multi_agent_plan(team_name, agents=[{name, role}, ...]) FIRST —
     this keeps the build loop open across multiple agents in one turn.
  2. build_agent(...) once per declared agent — each is independently built,
     verified, and tested exactly like any single agent (same rules apply:
     don't ask for confirmation, pick tools/model yourself).
  3. create_team(name, member_agent_ids=[...], team_type="collaborative" or
     "hierarchical", lead_agent_id=<if hierarchical>).
  4. Report each member's status (active vs needs_attention) and the team
     as a whole. Note: there is no automatic pipeline execution yet — each
     member agent runs independently when triggered; you are wiring them
     together as a team record, not building a live orchestration engine.

DO NOT declare a multi-agent plan for an ordinary single-agent request just
because the goal mentions several steps (e.g. "search the web, then write a
summary, then email it" is still ONE agent with three tools — not a team).
</team_dispatching>"""
