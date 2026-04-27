"""Training data for the Architect's own neural tool classifier.

Groups the architect's 125 tools into intent clusters so only the relevant
subset gets injected into the LLM prompt per user message.

Each sample: (user_message, correct_tool_group)

Tool groups (14 clusters + none):
  build       — create/build/modify agents, check tools, classify, repo-to-agent
  run         — execute/stop/cancel/approve sessions, emergency stop
  schedule    — create/list/update/delete schedules, triggers, webhooks
  inspect     — view agents, sessions, steps, metrics, providers, versions
  memory      — user memory, agent memory, RAG, insights, knowledge
  plan        — TODO tasks, brainstorm, workspace plan
  delegate    — delegate to other agents, multi-agent workflows
  workspace   — workspace name, databases, credits, integrations, time
  teams       — team management, members, workflows, NFTs, rentals
  marketplace — publish/unpublish agents, marketplace listings, APIs
  federation  — federated agents, cross-node tasks, heartbeat
  governance  — compliance, audit trail, governance evaluation
  learning    — patterns, recommendations, feedback, classifier
  advanced    — anomaly detection, templates, limits, direct tool execution
"""
from typing import List, Tuple

TrainingSample = Tuple[str, str]


def get_training_data() -> List[TrainingSample]:
    samples: List[TrainingSample] = []

    # ── BUILD: create/modify agents, tool selection ──
    _b = "build"
    samples += [
        ("create an agent that scrapes YCombinator", _b),
        ("build me a web scraper agent", _b),
        ("make an agent to monitor stock prices", _b),
        ("create a research agent for AI news", _b),
        ("build an email agent that sends daily digests", _b),
        ("I need a new agent for social media monitoring", _b),
        ("set up an agent to track competitors", _b),
        ("create an automation agent for lead generation", _b),
        ("modify my scraper agent to add email tool", _b),
        ("add web_search tool to my research agent", _b),
        ("remove the email tool from that agent", _b),
        ("change my agent's model to GPT-4o", _b),
        ("update the temperature to 0.3", _b),
        ("update my agent's system prompt", _b),
        ("change the instructions for my research agent", _b),
        ("rewrite the prompt to be more detailed", _b),
        ("what tools should this agent have", _b),
        ("which tools are available for agents", _b),
        ("list all platform tools", _b),
        ("what tools can I give my agent", _b),
        ("refine agent instructions", _b),
        ("improve my agent's prompt", _b),
        ("make the agent better at scraping", _b),
        ("optimize my agent", _b),
        ("build an agent for data analysis", _b),
        ("create a code review agent", _b),
        ("make a content writing agent", _b),
        ("set up an agent to post on twitter", _b),
        ("I want to create an agent", _b),
        ("new agent please", _b),
        ("connect google sheets to my agent", _b),
        ("add google sheets tool", _b),
        ("make an agent that reads my spreadsheet", _b),
        ("build an agent to update my google sheet", _b),
        ("create an agent that sends emails", _b),
        ("add email tool to my agent", _b),
        ("I want my agent to send gmail", _b),
        ("connect gmail to my agent", _b),
        ("make an agent that creates google docs", _b),
        ("add google docs tool", _b),
        ("build an agent to write documents", _b),
        ("set up an agent for spreadsheet automation", _b),
        ("create an agent that reads and writes sheets", _b),
    ]

    # ── RUN: execute, stop, cancel, approve, emergency ──
    _r = "run"
    samples += [
        ("run my scraper agent", _r),
        ("execute the research agent now", _r),
        ("start my agent", _r),
        ("run it", _r),
        ("execute the agent", _r),
        ("stop my agent", _r),
        ("cancel the running session", _r),
        ("stop all running agents", _r),
        ("emergency stop everything", _r),
        ("kill all running sessions", _r),
        ("cancel that session", _r),
        ("halt the agent immediately", _r),
        ("abort the current run", _r),
        ("approve the pending action", _r),
        ("reject that step", _r),
        ("what's waiting for approval", _r),
        ("are there any pending approvals", _r),
        ("run the agent with a different goal", _r),
        ("start a new session for my agent", _r),
        ("try running it again", _r),
    ]

    # ── SCHEDULE: create/list/update/delete schedules, triggers ──
    _s = "schedule"
    samples += [
        ("schedule my agent to run daily at 9am", _s),
        ("set up a schedule for every hour", _s),
        ("run this agent every Monday", _s),
        ("create a cron schedule", _s),
        ("set a trigger for my agent", _s),
        ("what schedules do I have", _s),
        ("list schedules for my agent", _s),
        ("delete the daily schedule", _s),
        ("disable the schedule", _s),
        ("update the schedule to run weekly", _s),
        ("change the schedule to 6am", _s),
        ("stop the recurring schedule", _s),
        ("I want it to run automatically every day", _s),
        ("set up automation for my agent", _s),
        ("how often does my agent run", _s),
    ]

    # ── INSPECT: view agents, sessions, steps, metrics, providers ──
    _i = "inspect"
    samples += [
        ("show me my agents", _i),
        ("list all agents", _i),
        ("how many agents do I have", _i),
        ("what agents exist in my workspace", _i),
        ("show agent details", _i),
        ("show me the session history", _i),
        ("what did my agent do in the last run", _i),
        ("show the execution steps", _i),
        ("show me the trace for that session", _i),
        ("what's the agent's performance", _i),
        ("show metrics for my scraper", _i),
        ("what was the success rate", _i),
        ("how many sessions has it run", _i),
        ("which providers are available", _i),
        ("what LLM models can I use", _i),
        ("is OpenAI working", _i),
        ("check provider status", _i),
        ("show me agent versions", _i),
        ("what's the agent's current config", _i),
        ("show me what happened", _i),
    ]

    # ── MEMORY: user/agent memory, RAG, insights ──
    _m = "memory"
    samples += [
        ("what do you remember about me", _m),
        ("save this preference", _m),
        ("remember that I prefer GPT-4o", _m),
        ("what has my agent learned", _m),
        ("show agent memory", _m),
        ("search memory for previous results", _m),
        ("what did we discuss last time", _m),
        ("recall previous agent configurations", _m),
        ("store this insight", _m),
        ("what patterns have you noticed", _m),
        ("what context do you have", _m),
        ("get your accumulated knowledge", _m),
        ("what do you know from past sessions", _m),
    ]

    # ── PLAN: TODO tasks, brainstorm, workspace plan ──
    _p = "plan"
    samples += [
        ("create a task to fix the scraper", _p),
        ("add a TODO item", _p),
        ("what's on my task list", _p),
        ("show me the plan", _p),
        ("update the task status to completed", _p),
        ("mark that task as done", _p),
        ("I have an idea for a new agent workflow", _p),
        ("brainstorm ways to improve my agents", _p),
        ("what's the workspace plan", _p),
        ("show all tasks across agents", _p),
        ("create a plan for building an agent pipeline", _p),
        ("list my pending tasks", _p),
        ("what's the priority of my tasks", _p),
    ]

    # ── DELEGATE: multi-agent orchestration ──
    _d = "delegate"
    samples += [
        ("ask my research agent to find info about Tesla", _d),
        ("delegate this task to the scraper agent", _d),
        ("use my email agent to send the results", _d),
        ("have my writer agent create a blog post", _d),
        ("run the analysis agent on this data", _d),
        ("tell my monitor agent to check for changes", _d),
        ("chain these agents together", _d),
        ("use agent X to do Y", _d),
        ("delegate to the data agent", _d),
        ("ask another agent to handle this", _d),
    ]

    # ── WORKSPACE: settings, credits, integrations, time ──
    _w = "workspace"
    samples += [
        ("rename my workspace", _w),
        ("what's my credit balance", _w),
        ("how many credits do I have", _w),
        ("check my integrations", _w),
        ("is Google connected", _w),
        ("what's connected", _w),
        ("which OAuth services are linked", _w),
        ("what time is it", _w),
        ("show workspace databases", _w),
        ("what plan am I on", _w),
        ("check my billing", _w),
        ("delete all agents", _w),
        ("clean up the workspace", _w),
    ]

    # ── BUILD extras: repo-to-agent, templates ──
    samples += [
        ("convert this github repo to an agent", _b),
        ("analyze this repository", _b),
        ("turn my github project into an agent", _b),
        ("import agent from repo", _b),
    ]

    # ── TEAMS: team management, members, workflows, NFTs ──
    _tm = "teams"
    samples += [
        ("create a new team", _tm),
        ("show me my teams", _tm),
        ("add a member to my team", _tm),
        ("list team members", _tm),
        ("delete the marketing team", _tm),
        ("update team settings", _tm),
        ("what team workflows are running", _tm),
        ("cancel the team workflow", _tm),
        ("archive the old team", _tm),
        ("restore the archived team", _tm),
        ("mint an NFT for my team", _tm),
        ("rent access to this team", _tm),
        ("transfer team ownership", _tm),
        ("check team rental status", _tm),
        ("show my rentals", _tm),
    ]

    # ── MARKETPLACE: publish, list, APIs ──
    _mk = "marketplace"
    samples += [
        ("publish my agent to the marketplace", _mk),
        ("list marketplace agents", _mk),
        ("remove my agent from marketplace", _mk),
        ("how much should I charge for my agent", _mk),
        ("publish my agent as an API", _mk),
        ("unpublish the agent API", _mk),
        ("show published APIs for my agent", _mk),
        ("delete the published API", _mk),
        ("call a public agent API", _mk),
        ("show marketplace listings", _mk),
        ("I want to sell my agent", _mk),
        ("make my agent available to others", _mk),
    ]

    # ── FEDERATION: cross-node agents ──
    _fd = "federation"
    samples += [
        ("show federated agents", _fd),
        ("register for federation", _fd),
        ("connect to another node", _fd),
        ("disconnect federated agent", _fd),
        ("check federation status", _fd),
        ("send federation heartbeat", _fd),
        ("poll for federation tasks", _fd),
        ("submit federation result", _fd),
        ("list agents from other nodes", _fd),
        ("federate my agent", _fd),
    ]

    # ── GOVERNANCE: compliance, audit ──
    _gv = "governance"
    samples += [
        ("check compliance score", _gv),
        ("show the audit trail", _gv),
        ("generate compliance report", _gv),
        ("evaluate governance for this action", _gv),
        ("export audit data", _gv),
        ("show evidence checklist", _gv),
        ("is this action compliant", _gv),
        ("what's our compliance status", _gv),
        ("review governance policies", _gv),
        ("audit log for my agents", _gv),
    ]

    # ── LEARNING: patterns, recommendations, feedback ──
    _ln = "learning"
    samples += [
        ("what patterns have my agents learned", _ln),
        ("get recommendations for my agent", _ln),
        ("show learning statistics", _ln),
        ("what has the system learned", _ln),
        ("give feedback on that session", _ln),
        ("rate the last run", _ln),
        ("how can I improve my agent", _ln),
        ("show classifier stats", _ln),
        ("retrain the tool classifier", _ln),
        ("what knowledge has my agent accumulated", _ln),
        ("suggest improvements for my agents", _ln),
    ]

    # ── ADVANCED: anomaly, templates, limits, direct execution ──
    _ad = "advanced"
    samples += [
        ("set up anomaly detection", _ad),
        ("create an anomaly trigger", _ad),
        ("list anomaly triggers", _ad),
        ("delete the anomaly trigger", _ad),
        ("fire the anomaly trigger for testing", _ad),
        ("show available templates", _ad),
        ("create agent from template", _ad),
        ("what are the platform limits", _ad),
        ("update the rate limit", _ad),
        ("execute this tool directly", _ad),
        ("test the web_search tool", _ad),
        ("get the async tool result", _ad),
    ]

    # ── GENERAL CHAT (no tools needed) ──
    _n = "none"
    samples += [
        ("hello", _n),
        ("hi there", _n),
        ("thanks", _n),
        ("what can you do", _n),
        ("how does this work", _n),
        ("explain agents to me", _n),
        ("what is an AI agent", _n),
        ("goodbye", _n),
        ("ok", _n),
        ("sure", _n),
        ("that's cool", _n),
        ("interesting", _n),
        ("tell me more", _n),
        ("I don't understand", _n),
        ("help", _n),
    ]

    return samples
