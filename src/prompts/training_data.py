"""Seed Training Data for Neural Prompt Classifier.

Each sample: (user_message, list_of_prompt_module_ids_to_inject)

The classifier learns which prompt modules are relevant for each type
of user message. Only NON-BASE modules are predicted — base modules
(identity, platform, rules, style) are always injected.

Active learning: every prediction is logged and used during retraining.
"""
from typing import List, Tuple

# Type: (message, [module_ids])
TrainingSample = Tuple[str, List[str]]


def get_training_data() -> List[TrainingSample]:
    """Return seed training dataset."""
    samples: List[TrainingSample] = []

    # ── BRAINSTORM mode ──
    samples += [
        ("I want to build an agent", ["brainstorm"]),
        ("what can you do", ["brainstorm"]),
        ("help me automate my business", ["brainstorm"]),
        ("I want to automate stuff", ["brainstorm"]),
        ("what kind of agents can I build", ["brainstorm"]),
        ("I need help with automation", ["brainstorm"]),
        ("can you build me something", ["brainstorm"]),
        ("I spend too much time on repetitive tasks", ["brainstorm"]),
        ("let's build something cool", ["brainstorm"]),
        ("what should I automate first", ["brainstorm"]),
        ("I want an agent but I'm not sure what kind", ["brainstorm"]),
        ("help me think about what agents would be useful", ["brainstorm"]),
        ("what automation makes sense for a startup", ["brainstorm"]),
        ("I'm new here, what can agents do", ["brainstorm"]),
        ("show me what's possible with agents", ["brainstorm"]),
    ]

    # ── CONTROL + RESEARCH mood ──
    samples += [
        ("build an agent that researches AI news daily", ["goal_crafting", "dispatching", "mood_researcher", "tool_synergies", "models_config"]),
        ("create a research agent for market analysis", ["goal_crafting", "dispatching", "mood_researcher", "tool_synergies", "models_config"]),
        ("I need an agent that summarizes tech news", ["goal_crafting", "dispatching", "mood_researcher", "tool_synergies"]),
        ("make an agent that reads HackerNews and sends briefings", ["goal_crafting", "dispatching", "mood_researcher", "tool_synergies"]),
        ("build a news research agent", ["goal_crafting", "dispatching", "mood_researcher", "tool_synergies"]),
        ("create an agent to research competitors", ["goal_crafting", "dispatching", "mood_researcher", "tool_synergies"]),
        ("I want an agent that does deep research on topics", ["goal_crafting", "dispatching", "mood_researcher", "tool_synergies"]),
        ("build me a morning briefing agent", ["goal_crafting", "dispatching", "mood_researcher", "tool_synergies"]),
    ]

    # ── CONTROL + SCRAPER mood ──
    samples += [
        ("scrape Y Combinator for startups", ["goal_crafting", "dispatching", "scope_risk", "mood_scraper", "tool_synergies", "models_config"]),
        ("build a web scraper agent", ["goal_crafting", "dispatching", "scope_risk", "mood_scraper", "tool_synergies"]),
        ("create an agent that scrapes websites for data", ["goal_crafting", "dispatching", "scope_risk", "mood_scraper", "tool_synergies"]),
        ("I need to scrape competitor pricing pages", ["goal_crafting", "dispatching", "scope_risk", "mood_scraper", "tool_synergies"]),
        ("build an agent to crawl product listings", ["goal_crafting", "dispatching", "scope_risk", "mood_scraper", "tool_synergies"]),
        ("scrape Reddit for mentions of my product", ["goal_crafting", "dispatching", "mood_scraper", "tool_synergies"]),
        ("create a scraper for job listings on LinkedIn", ["goal_crafting", "dispatching", "scope_risk", "mood_scraper", "tool_synergies"]),
        ("scrape all restaurants in San Francisco with reviews", ["goal_crafting", "dispatching", "scope_risk", "mood_scraper", "tool_synergies"]),
    ]

    # ── CONTROL + MONITOR mood ──
    samples += [
        ("monitor my competitor's website for changes", ["goal_crafting", "dispatching", "mood_monitor", "tool_synergies"]),
        ("build an agent that watches for price drops", ["goal_crafting", "dispatching", "mood_monitor", "tool_synergies"]),
        ("create a monitoring agent for website uptime", ["goal_crafting", "dispatching", "mood_monitor", "tool_synergies"]),
        ("I want to track changes on a webpage", ["goal_crafting", "dispatching", "mood_monitor", "tool_synergies"]),
        ("monitor stock prices and alert me", ["goal_crafting", "dispatching", "mood_monitor", "tool_synergies"]),
        ("watch HackerNews for posts about my company", ["goal_crafting", "dispatching", "mood_monitor", "tool_synergies"]),
        ("build an alert system for job postings", ["goal_crafting", "dispatching", "mood_monitor", "tool_synergies"]),
        ("track when a specific page updates", ["goal_crafting", "dispatching", "mood_monitor", "tool_synergies"]),
    ]

    # ── CONTROL + SALES mood ──
    samples += [
        ("build a lead generation agent", ["goal_crafting", "dispatching", "scope_risk", "mood_sales", "tool_synergies"]),
        ("create a sales outreach agent", ["goal_crafting", "dispatching", "mood_sales", "tool_synergies"]),
        ("automate my sales pipeline follow-ups", ["goal_crafting", "dispatching", "mood_sales", "tool_synergies"]),
        ("build an agent for cold email outreach", ["goal_crafting", "dispatching", "mood_sales", "tool_synergies"]),
        ("find leads in my target market", ["goal_crafting", "dispatching", "scope_risk", "mood_sales", "tool_synergies"]),
        ("create a prospecting agent for SaaS companies", ["goal_crafting", "dispatching", "scope_risk", "mood_sales", "tool_synergies"]),
        ("automate CRM updates from email conversations", ["goal_crafting", "dispatching", "mood_sales", "tool_synergies", "authentication"]),
        ("build an agent that nurtures leads automatically", ["goal_crafting", "dispatching", "mood_sales", "tool_synergies"]),
    ]

    # ── CONTROL + CONTENT mood ──
    samples += [
        ("create a content writing agent", ["goal_crafting", "dispatching", "mood_content", "tool_synergies"]),
        ("build an agent that writes blog posts", ["goal_crafting", "dispatching", "mood_content", "tool_synergies"]),
        ("make a newsletter generation agent", ["goal_crafting", "dispatching", "mood_content", "tool_synergies"]),
        ("build an agent to write social media content", ["goal_crafting", "dispatching", "mood_content", "mood_social", "tool_synergies"]),
        ("create an agent that generates marketing copy", ["goal_crafting", "dispatching", "mood_content", "tool_synergies"]),
        ("automate my weekly newsletter", ["goal_crafting", "dispatching", "mood_content", "tool_synergies"]),
        ("build a content curation agent", ["goal_crafting", "dispatching", "mood_content", "tool_synergies"]),
    ]

    # ── CONTROL + CODE mood ──
    samples += [
        ("build an agent that analyzes my GitHub repos", ["goal_crafting", "dispatching", "mood_code", "tool_synergies"]),
        ("create a code review agent", ["goal_crafting", "dispatching", "mood_code", "tool_synergies"]),
        ("build an agent to scan for security vulnerabilities", ["goal_crafting", "dispatching", "mood_code", "tool_synergies"]),
        ("automate code documentation", ["goal_crafting", "dispatching", "mood_code", "tool_synergies"]),
        ("create an agent that runs tests on my repo", ["goal_crafting", "dispatching", "mood_code", "tool_synergies"]),
        ("build a CI/CD monitoring agent", ["goal_crafting", "dispatching", "mood_code", "mood_monitor", "tool_synergies"]),
    ]

    # ── CONTROL + EMAIL mood ──
    samples += [
        ("build an agent that sends daily reports by email", ["goal_crafting", "dispatching", "mood_email", "tool_synergies"]),
        ("create an email automation agent", ["goal_crafting", "dispatching", "mood_email", "tool_synergies", "authentication"]),
        ("automate sending follow-up emails", ["goal_crafting", "dispatching", "mood_email", "mood_sales", "tool_synergies"]),
        ("build an agent that reads my inbox and summarizes", ["goal_crafting", "dispatching", "mood_email", "tool_synergies", "authentication"]),
        ("send me email alerts when something changes", ["goal_crafting", "dispatching", "mood_email", "mood_monitor", "tool_synergies"]),
    ]

    # ── CONTROL + DATA mood ──
    samples += [
        ("build an agent that collects data and makes a spreadsheet", ["goal_crafting", "dispatching", "scope_risk", "mood_data", "tool_synergies"]),
        ("create a data analysis agent", ["goal_crafting", "dispatching", "mood_data", "tool_synergies"]),
        ("I need to collect data from multiple sources into a CSV", ["goal_crafting", "dispatching", "mood_data", "tool_synergies"]),
        ("build an agent that generates Excel reports", ["goal_crafting", "dispatching", "mood_data", "tool_synergies"]),
        ("scrape data and organize into a spreadsheet", ["goal_crafting", "dispatching", "scope_risk", "mood_data", "mood_scraper", "tool_synergies"]),
        ("analyze website traffic data", ["goal_crafting", "dispatching", "mood_data", "tool_synergies"]),
    ]

    # ── CONTROL + SOCIAL mood ──
    samples += [
        ("build an agent for social media monitoring", ["goal_crafting", "dispatching", "mood_social", "tool_synergies"]),
        ("create an agent that posts to Twitter", ["goal_crafting", "dispatching", "mood_social", "tool_synergies", "authentication"]),
        ("monitor Reddit for mentions of my brand", ["goal_crafting", "dispatching", "mood_social", "mood_monitor", "tool_synergies"]),
        ("track LinkedIn posts about AI", ["goal_crafting", "dispatching", "mood_social", "tool_synergies"]),
        ("build a community engagement bot", ["goal_crafting", "dispatching", "mood_social", "tool_synergies"]),
    ]

    # ── CONTROL + INTEGRATION mood ──
    samples += [
        ("connect my Google Drive with Notion", ["goal_crafting", "dispatching", "mood_integration", "authentication"]),
        ("build an agent that syncs data between services", ["goal_crafting", "dispatching", "mood_integration", "tool_synergies", "authentication"]),
        ("automate my workflow between Slack and Jira", ["goal_crafting", "dispatching", "mood_integration", "tool_synergies", "authentication"]),
        ("create a data pipeline between APIs", ["goal_crafting", "dispatching", "mood_integration", "tool_synergies"]),
        ("sync my CRM with email marketing platform", ["goal_crafting", "dispatching", "mood_integration", "mood_sales", "authentication"]),
    ]

    # ── CONTROL: simple management (no mood) ──
    samples += [
        ("run my agent", ["dispatching"]),
        ("start the scraper agent", ["dispatching"]),
        ("stop my running agent", ["dispatching"]),
        ("delete all agents", ["dispatching"]),
        ("delete the test agent", ["dispatching"]),
        ("schedule my agent to run daily", ["dispatching"]),
        ("set a trigger for my agent", ["dispatching"]),
        ("add web_search tool to my agent", ["dispatching"]),
        ("modify my agent's configuration", ["dispatching", "models_config"]),
        ("change the model to GPT-4", ["dispatching", "models_config"]),
        ("increase max loops to 50", ["dispatching", "models_config"]),
        ("rename my workspace", ["dispatching", "naming"]),
    ]

    # ── REVIEW mode ──
    samples += [
        ("how many agents do I have", ["review"]),
        ("show my agents", ["review"]),
        ("list all agents", ["review"]),
        ("what happened on the last run", ["review"]),
        ("show me the results of my agent", ["review"]),
        ("what's my credit balance", ["review"]),
        ("how much did that run cost", ["review"]),
        ("show agent history", ["review"]),
        ("what agents are running right now", ["review"]),
        ("status of my workspace", ["review"]),
    ]

    # ── DIAGNOSE mode ──
    samples += [
        ("my agent is not working", ["diagnose"]),
        ("why does my agent keep failing", ["diagnose"]),
        ("the scraper agent is broken", ["diagnose"]),
        ("agent output quality is bad", ["diagnose"]),
        ("my agent hits the loop limit every time", ["diagnose", "models_config"]),
        ("fix my failing agent", ["diagnose"]),
        ("the agent keeps timing out", ["diagnose"]),
        ("debug my research agent", ["diagnose"]),
        ("something went wrong with the last run", ["diagnose"]),
        ("agent produces empty results", ["diagnose"]),
    ]

    # ── RUN EVENTS ──
    samples += [
        ("[Run Event] build SUCCESS agent_id=abc123", ["run_events"]),
        ("[Run Event] build FAIL agent_id=abc123", ["run_events", "diagnose"]),
        ("[Run Event] run SUCCESS agent_id=abc123", ["run_events"]),
        ("[Run Event] run PARTIAL agent_id=abc123", ["run_events", "diagnose"]),
        ("[Run Event] run FAIL agent_id=abc123 error=loop_limit", ["run_events", "diagnose"]),
    ]

    # ── SCOPE RISK triggers ──
    samples += [
        ("find all companies in California", ["goal_crafting", "scope_risk", "dispatching", "mood_scraper"]),
        ("scrape every restaurant in New York", ["goal_crafting", "scope_risk", "dispatching", "mood_scraper"]),
        ("get all job listings across all major cities", ["goal_crafting", "scope_risk", "dispatching", "mood_scraper"]),
        ("find leads in every US state", ["goal_crafting", "scope_risk", "dispatching", "mood_sales"]),
        ("collect data from all Fortune 500 websites", ["goal_crafting", "scope_risk", "dispatching", "mood_data"]),
    ]

    # ── NAMING triggers ──
    samples += [
        ("this is my first agent build something for research", ["brainstorm", "naming"]),
        ("create my first agent in this workspace", ["goal_crafting", "dispatching", "naming"]),
    ]

    return samples
