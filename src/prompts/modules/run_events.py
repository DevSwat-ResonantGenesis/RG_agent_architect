"""Run events — how to handle build/run completion events."""

ID = "run_events"
TAGS = ["event", "lifecycle"]
ALWAYS = False

PROMPT = """<run_events>
[Run Event] messages are system-generated, NOT user messages.

CRITICAL: Never call run_agent/build_agent/continue_build in response to a [Run Event] unless user explicitly asked. Inform, propose follow-ups, wait.

Build SUCCESS (no trigger): Summarize. If goal implies recurrence, call set_trigger proactively. present_options: ["Set up a schedule", "Try a test run", "Adjust the agent"]
Build SUCCESS (has trigger): Summarize. present_options: ["Try a test run", "Adjust the agent"]
Build PARTIAL/FAIL: Call run_snapshot to diagnose. Explain. present_options: ["Fix the issue", "Try different approach", "Show details"]
Run SUCCESS: Summarize results. present_options: ["Run again", "Make changes", "Set up a schedule"]
Run PARTIAL/FAIL: Call run_snapshot. Explain what worked/didn't. present_options: ["Fix with rebuild", "Run again", "Show details"]
</run_events>"""
