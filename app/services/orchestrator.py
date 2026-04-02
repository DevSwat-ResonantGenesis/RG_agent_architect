"""
RG Agent Architect — Main Orchestrator
Entry point for all Agent Architect requests. Routes by intent, manages state,
builds responses with follow-up options.
"""
import logging
import re

from .prompts import (
    INTENT_CLASSIFY_PROMPT,
    HIGH_RISK_PATTERNS,
    MODERATE_RISK_PATTERNS,
)
from .llm_client import llm_fast, llm_json
from .context import fetch_workspace_context, store_memory
from .builder import (
    generate_blueprint,
    generate_brainstorm,
    generate_modification,
    apply_modification,
    create_agents_from_blueprint,
    create_single_agent,
    build_simple_payload,
)
from .runner import (
    run_agent_full,
    run_agents_batch,
    parse_schedule_from_message,
    create_schedule,
    fetch_agent_sessions,
)

logger = logging.getLogger(__name__)

PANEL_URL = "/agents?embed=1"


# ═══════════════════════════════════════════════════════════════
# MAIN ORCHESTRATE ENTRY POINT
# ═══════════════════════════════════════════════════════════════

async def orchestrate(
    message: str,
    user_id: str,
    context: dict,
    headers: dict[str, str],
    user_api_keys: dict | None = None,
) -> dict:
    """Main orchestration entry point. Called by the /orchestrate endpoint.

    Flow:
    1. Fetch workspace context (agents, tools, memory) in parallel
    2. Check if this is a confirmation of a prior plan
    3. Classify intent
    4. Route to appropriate handler
    5. Return structured response with summary + follow-up options
    """
    logger.info(f"🏗️ [ORCHESTRATE] Message: {message[:120]!r}")

    # Step 0: Context Protocol — gather workspace state
    workspace = await fetch_workspace_context(user_id, headers)
    agents = workspace.get("agents", [])
    agent_count = len(agents)

    logger.info(f"🏗️ [ORCHESTRATE] Context: {agent_count} agents, tools={workspace.get('tools_summary')}")

    # Step 1: Check confirmation
    if _is_confirmation(message, context):
        original = _extract_original_request(context)
        logger.info(f"🏗️ [ORCHESTRATE] Confirmation → build: {original[:100]!r}")
        return await _handle_build_execute(
            original, user_id, headers, user_api_keys, workspace, agents,
        )

    # Step 2: Classify intent
    intent = await _classify_intent(message, user_api_keys)
    logger.info(f"🏗️ [ORCHESTRATE] Intent: {intent}")

    # Step 3: Route by intent
    if intent == "BRAINSTORM":
        return await _handle_brainstorm(message, agents, workspace, user_api_keys)
    if intent == "REVIEW":
        return _handle_review(agents)
    if intent == "MODIFY":
        return await _handle_modify(message, agents, headers, user_api_keys)
    if intent == "DIAGNOSE":
        return await _handle_diagnose(message, agents, headers)
    if intent == "RUN":
        return await _handle_run(message, agents, headers)
    if intent == "SCHEDULE":
        return await _handle_schedule(message, agents, headers)

    # BUILD intent: Phase 1 — plan preview
    return await _handle_build_preview(
        message, user_id, headers, user_api_keys, workspace, agents,
    )


# ═══════════════════════════════════════════════════════════════
# INTENT CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

async def _classify_intent(message: str, user_api_keys: dict | None = None) -> str:
    """Classify intent: regex shortcuts first, then LLM fallback."""
    msg = re.sub(r"^agent\s*architect\s*:\s*", "", message.lower().strip())

    # Quick regex (order: most specific first)
    if any(kw in msg for kw in ("what agents", "list agents", "show agents", "my agents", "how many agents")):
        return "REVIEW"
    if any(kw in msg for kw in ("why did", "failed", "what went wrong", "error", "diagnose", "debug")):
        return "DIAGNOSE"
    if any(kw in msg for kw in ("change my", "update my", "modify my", "add tool", "remove tool", "change schedule")):
        return "MODIFY"
    if re.search(r"\b(run|execute|start|trigger|launch)\s+(?:the\s+|my\s+|this\s+)?[A-Z]", message.strip()):
        return "RUN"
    if re.search(r"\b(run|execute|start|trigger)\b.*\b(now|agent|it|again)\b", msg):
        return "RUN"
    if any(kw in msg for kw in ("create", "build", "make me", "set up", "deploy", "i need an agent", "i want an agent")):
        return "BUILD"
    # BRAINSTORM: vague exploration, no concrete outcome
    if any(kw in msg for kw in ("not sure", "what can", "what kind", "help me", "ideas", "explore", "possibilities", "don't know", "dont know")):
        return "BRAINSTORM"
    if re.search(r"\b(automate|automation)\b", msg) and not re.search(r"\b(every|daily|hourly|weekly|schedule|cron)\b", msg):
        return "BRAINSTORM"
    # SCHEDULE: only when time-specific patterns present
    if re.search(r"\b(schedule|recurring|cron|every\s+(?:day|hour|week|morning|evening|\d+\s*min))\b", msg):
        return "SCHEDULE"

    # LLM fallback
    prompt = INTENT_CLASSIFY_PROMPT.format(message=message[:500])
    text = await llm_fast(prompt, user_api_keys=user_api_keys)
    text_upper = text.upper()
    for intent in ("RUN", "SCHEDULE", "BRAINSTORM", "BUILD", "MODIFY", "DIAGNOSE", "REVIEW"):
        if intent in text_upper:
            return intent

    return "BUILD"  # safe default


# ═══════════════════════════════════════════════════════════════
# CONFIRMATION DETECTION
# ═══════════════════════════════════════════════════════════════

_CONFIRM_PATTERNS = [
    r"^(yes|yep|yeah|yup|sure|ok|okay|go|do it|confirm|approved|lgtm)\b",
    r"build\b.*\b(now|as planned|all|them|it)",
    r"yes.{0,20}build",
    r"looks? good",
    r"go ahead",
    r"as planned",
    r"create\b.*\b(it|them|now|all|agents?)",
    r"ship it",
    r"let'?s? (do it|go|build)",
    r"^(build|create|deploy|launch)$",
]


def _is_confirmation(message: str, context: dict) -> bool:
    """Detect if user is confirming a previous plan preview."""
    msg = re.sub(r"^agent\s*architect\s*:\s*", "", message.lower().strip())

    # Strong confirmation: exact button-click values we generate — always trust these
    _STRONG_CONFIRMS = {"yes, build it", "yes build it", "go ahead", "build it", "ship it", "do it", "yes", "confirm"}
    if msg in _STRONG_CONFIRMS:
        # Check ANY evidence of prior plan in context
        prev = context.get("messages") or context.get("previousMessages") or context.get("previous_messages") or []
        prev_content = context.get("prev_assistant_content") or ""
        has_preview = any(
            any(k in (m.get("content") or "") for k in ("Plan Preview", "Here's what I'll create", "Ready to build", "Mode: BUILD", "agent(s)"))
            for m in prev[-10:]
            if m.get("role") == "assistant"
        ) or any(k in prev_content for k in ("Plan Preview", "Ready to build", "agent(s)"))
        # Even without history, trust the button click if it has the exact value
        if has_preview or msg == "yes, build it":
            return True

    # Standard confirmation: requires history evidence
    prev = context.get("messages") or context.get("previousMessages") or context.get("previous_messages") or []
    has_preview = any(
        any(k in (m.get("content") or "") for k in ("Plan Preview", "Here's what I'll create", "Ready to build", "Mode: BUILD"))
        for m in prev[-5:]
        if m.get("role") == "assistant"
    )
    if not has_preview:
        return False
    return any(re.search(p, msg) for p in _CONFIRM_PATTERNS)


def _extract_original_request(context: dict) -> str:
    """Extract the original build request from conversation history."""
    prev = context.get("messages") or context.get("previousMessages") or context.get("previous_messages") or []
    user_msgs = [m.get("content", "") for m in prev if m.get("role") == "user" and m.get("content")]
    if len(user_msgs) >= 2:
        original = re.sub(r"^Agent\s*Architect\s*:\s*", "", user_msgs[-2]).strip()
        if original:
            return original
    for msg in reversed(user_msgs):
        clean = re.sub(r"^Agent\s*Architect\s*:\s*", "", msg).strip()
        if any(kw in clean.lower() for kw in ("build", "create", "make", "agent", "deploy", "set up")):
            return clean
    return user_msgs[-1] if user_msgs else "build an agent"


# ═══════════════════════════════════════════════════════════════
# SCOPE RISK ANALYSIS
# ═══════════════════════════════════════════════════════════════

def _assess_scope_risk(message: str) -> dict:
    """Analyze scope risk. Returns level + decision branches."""
    msg = message.lower()
    for pattern in HIGH_RISK_PATTERNS:
        if re.search(pattern, msg):
            return {
                "level": "high",
                "reason": "This could target thousands of items — potentially expensive.",
                "branches": [
                    {"label": "Run on 10 samples", "value": "Agent Architect: build this but limit to 10 items as a test", "description": "Safe starting point", "icon": "🧪", "default": True},
                    {"label": "Run on 100", "value": "Agent Architect: build this limited to 100 items", "description": "Medium scale validation", "icon": "📊"},
                    {"label": "Full scale", "value": "Agent Architect: build at full scale", "description": "Full power — may be costly", "icon": "🚀"},
                ],
            }
    for pattern in MODERATE_RISK_PATTERNS:
        if re.search(pattern, msg):
            return {
                "level": "moderate",
                "reason": "Multi-step processing that could scale up.",
                "branches": [
                    {"label": "Build with limits", "value": "Agent Architect: build with sensible rate limits", "description": "Safe default", "icon": "🛡️", "default": True},
                    {"label": "Build unrestricted", "value": "Agent Architect: build with no restrictions", "description": "Full power", "icon": "⚡"},
                ],
            }
    return {"level": "safe", "reason": None, "branches": None}


# ═══════════════════════════════════════════════════════════════
# HANDLER: BUILD PREVIEW (Phase 1)
# ═══════════════════════════════════════════════════════════════

async def _handle_build_preview(
    message: str,
    user_id: str,
    headers: dict[str, str],
    user_api_keys: dict | None,
    workspace: dict,
    agents: list[dict],
) -> dict:
    """Phase 1: Generate blueprint, show plan preview, wait for confirmation."""
    risk = _assess_scope_risk(message)
    platform_ctx = f"Resonant Genesis — AI agent platform ({workspace.get('tools_summary', '160+ tools')})"
    if workspace.get("memory_facts"):
        platform_ctx += f"\nUser info: {workspace['memory_facts'][:300]}"

    agents_str = "None yet"
    if agents:
        descs = [f"- {a['name']} ({a.get('model', '?')}, tools: {', '.join(a.get('tools', [])[:5])})" for a in agents[:10]]
        agents_str = "\n".join(descs)

    blueprint = await generate_blueprint(message, user_api_keys, platform_ctx, agents_str)

    if not blueprint or "agents" not in blueprint:
        # LLM planning failed — skip to direct build
        return await _handle_build_execute(message, user_id, headers, user_api_keys, workspace, agents)

    # Build plan preview summary
    bp_agents = blueprint.get("agents", [])
    reasoning = blueprint.get("reasoning", "")
    assumptions = blueprint.get("assumptions", [])

    summary = f"**Plan Preview** — {len(bp_agents)} agent(s)\n\n"
    if reasoning:
        summary += f"*{reasoning}*\n\n"
    summary += "---\n\n"

    for i, bp in enumerate(bp_agents):
        summary += f"**{i+1}. {bp.get('name', 'Agent')}**\n"
        summary += f"   {bp.get('description', '')}\n"
        summary += f"   🎯 {bp.get('goal', 'No goal specified')[:120]}\n"
        summary += f"   Model: `{bp.get('provider', 'groq')}/{bp.get('model', 'llama-3.3-70b-versatile')}`\n"
        summary += f"   Tools: {', '.join(bp.get('tools', [])[:6])}\n"
        if bp.get("schedule"):
            summary += f"   ⏰ Schedule: {bp['schedule']}\n"
        summary += "\n"

    if assumptions:
        summary += "**Assumptions:**\n"
        for a in assumptions[:5]:
            summary += f"- {a}\n"
        summary += "\n"

    # Scope risk warning
    if risk["level"] != "safe" and risk.get("branches"):
        summary += f"⚠️ **Scope risk: {risk['level']}** — {risk['reason']}\n\n"
        options = risk["branches"]
    else:
        options = [
            {"label": "Build it", "value": "Agent Architect: yes, build it", "description": "Create these agents now", "icon": "🏗️"},
            {"label": "Adjust something", "value": "Agent Architect: let me adjust — ", "description": "Change before building", "icon": "✏️"},
        ]

    return {
        "success": True,
        "action": "open_agents_panel",
        "panel_url": PANEL_URL,
        "operation": "plan_preview",
        "intent": "BUILD",
        "scope_risk": risk["level"],
        "blueprint": blueprint,
        "summary": summary,
        "present_options": {
            "_type": "present_options",
            "title": "Ready to build?",
            "options": options[:4],
            "allow_custom": True,
        },
    }


# ═══════════════════════════════════════════════════════════════
# HANDLER: BUILD EXECUTE (Phase 2)
# ═══════════════════════════════════════════════════════════════

async def _handle_build_execute(
    message: str,
    user_id: str,
    headers: dict[str, str],
    user_api_keys: dict | None,
    workspace: dict,
    agents: list[dict],
) -> dict:
    """Phase 2: Actually create agents, execute first run, return results."""
    import httpx as _httpx

    platform_ctx = f"Resonant Genesis ({workspace.get('tools_summary', '160+ tools')})"
    if workspace.get("memory_facts"):
        platform_ctx += f"\nUser info: {workspace['memory_facts'][:300]}"

    agents_str = "None yet"
    if agents:
        descs = [f"- {a['name']} ({a.get('model', '?')})" for a in agents[:10]]
        agents_str = "\n".join(descs)

    blueprint = await generate_blueprint(message, user_api_keys, platform_ctx, agents_str)

    if not blueprint or "agents" not in blueprint:
        # Ultimate fallback: simple builder
        payload = build_simple_payload(message)
        async with _httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            result = await create_single_agent(client, payload, headers)
        if result:
            return {
                "success": True,
                "action": "open_agents_panel",
                "panel_url": PANEL_URL,
                "operation": "build",
                "intent": "BUILD",
                "created_agents": [{"id": result.get("id"), "name": result.get("name")}],
                "summary": f"✅ **{result.get('name')}** created — `{result.get('id')}`\n\n*(Used simplified builder — LLM planning unavailable)*",
                "present_options": _build_options([result], agents),
            }
        return {
            "success": False,
            "action": "open_agents_panel",
            "panel_url": PANEL_URL,
            "error": "Agent creation failed",
            "summary": "❌ Could not create agent. Please try again or use the Agents panel.",
        }

    # Create agents from blueprint
    bp_agents = blueprint.get("agents", [])
    reasoning = blueprint.get("reasoning", "")
    team_name = blueprint.get("team_name")
    team_workflow = blueprint.get("team_workflow")

    logger.info(f"🏗️ [BUILD] Creating {len(bp_agents)} agents")
    created, details = await create_agents_from_blueprint(blueprint, user_id, headers)

    # Auto-execute first run
    exec_results = await run_agents_batch(created, bp_agents, headers)

    # Store memory
    if created:
        names = [c.get("name", "?") for c in created]
        await store_memory(
            user_id,
            f"User built {len(created)} agent(s): {', '.join(names)}. Request: {message[:200]}",
            {"type": "build_event", "agent_count": len(created), "agent_names": names},
        )

    # Build summary
    n_created = len(created)
    n_total = len(bp_agents)
    has_schedule = any(bp.get("schedule") for bp in bp_agents)

    summary = f"**{n_created}/{n_total} agents created**\n\n"
    if reasoning:
        summary += f"*{reasoning}*\n\n"
    summary += "---\n\n"
    summary += "\n\n".join(details)

    if team_name and n_created > 1:
        summary += f"\n\n**Team:** {team_name} ({team_workflow or 'sequential'} workflow)"

    # Execution results
    if exec_results:
        summary += "\n\n---\n\n**🚀 First Run:**\n\n"
        for er in exec_results:
            emoji = {"completed": "✅", "running": "🔄", "started": "🔄", "failed": "❌", "launch_failed": "⚠️"}.get(er.get("status", ""), "❓")
            summary += f"- {emoji} **{er['agent_name']}** — {er.get('status', 'unknown')}"
            if er.get("steps"):
                summary += f" ({er['steps']} steps)"
            if er.get("output"):
                summary += f"\n  📋 {str(er['output'])[:200]}"
            if er.get("error") and er["status"] in ("failed", "launch_failed"):
                summary += f" — {er['error'][:100]}"
            summary += "\n"

    # Follow-up options
    any_running = any(er.get("status") in ("running", "started") for er in exec_results)
    any_completed = any(er.get("status") == "completed" for er in exec_results)
    any_failed = any(er.get("status") in ("failed", "launch_failed") for er in exec_results)

    options = []
    if any_running and created:
        first = created[0]
        options.append({"label": f"Check status of {first.get('name', 'agent')}", "value": f"Agent Architect: what's the status of {first.get('name', 'agent')}?", "description": "See if run completed", "icon": "🔍"})
    if any_completed and not has_schedule:
        options.append({"label": "Set up schedule", "value": f"Agent Architect: schedule {created[0].get('name', 'agent')} daily", "description": "Automate recurring runs", "icon": "⏰"})
    if any_failed and created:
        options.append({"label": "Diagnose issues", "value": f"Agent Architect: diagnose {created[0].get('name', 'agent')}", "description": "Investigate what went wrong", "icon": "🔧"})
    options.append({"label": "Build another", "value": "Agent Architect: build another agent", "description": "Create something new", "icon": "➕"})

    return {
        "success": n_created > 0,
        "action": "open_agents_panel",
        "panel_url": PANEL_URL,
        "operation": "build",
        "intent": "BUILD",
        "agent_count": n_created,
        "created_agents": [
            {"id": c.get("id"), "name": c.get("name"), "hash": c.get("agent_public_hash")}
            for c in created
        ],
        "execution_results": exec_results,
        "blueprint": blueprint,
        "summary": summary,
        "present_options": {
            "_type": "present_options",
            "title": "What's next?",
            "options": options[:4],
            "allow_custom": True,
        },
    }


# ═══════════════════════════════════════════════════════════════
# HANDLER: BRAINSTORM
# ═══════════════════════════════════════════════════════════════

async def _handle_brainstorm(
    message: str,
    agents: list[dict],
    workspace: dict,
    user_api_keys: dict | None,
) -> dict:
    """Opinionated proposals based on user context."""
    agent_summary = "Fresh workspace — no agents yet."
    if agents:
        names = [a.get("name", "?") for a in agents[:10]]
        agent_summary = f"{len(agents)} existing agents: {', '.join(names)}"

    proposals = await generate_brainstorm(
        message,
        workspace.get("memory_facts", ""),
        agent_summary,
        workspace.get("tools_summary", "160+ tools"),
        user_api_keys,
    )

    if proposals and proposals.get("proposals"):
        intro = proposals.get("intro", "Here's what I'd build based on your situation.")
        items = proposals["proposals"][:3]

        lines = [f"**{intro}**\n"]
        if workspace.get("memory_facts"):
            lines.append(f"*Context: {workspace['memory_facts'][:150]}*\n")
        for i, p in enumerate(items):
            lines.append(f"**{i+1}. {p.get('name', 'Agent')}**")
            lines.append(f"   {p.get('description', '')}")
            if p.get("why"):
                lines.append(f"   *Why:* {p['why']}")
            lines.append("")

        options = []
        for p in items:
            name = p.get("name", "Agent")
            options.append({
                "label": f"Build {name}",
                "value": f"Agent Architect: build me a {name} — {p.get('description', '')[:80]}",
                "description": p.get("description", "")[:80],
                "icon": "🏗️",
            })
        options.append({"label": "I have my own idea", "value": "Agent Architect: I have a specific idea —", "description": "Describe what you need", "icon": "✏️"})
    else:
        lines = [
            "**Here's what I'd build for you:**\n",
            "**1. Research Monitor** — Searches the web daily for specific topics, stores findings, sends digest.",
            "**2. Workflow Automator** — Connects tools (Drive, Calendar, GitHub) into automated pipelines.",
            "**3. Community Agent** — Monitors Rabbit communities and auto-responds or posts on schedule.",
            "",
        ]
        options = [
            {"label": "Research Monitor", "value": "Agent Architect: build a Research Monitor that searches the web daily and sends digest emails", "description": "Web monitoring + digests", "icon": "🏗️"},
            {"label": "Workflow Automator", "value": "Agent Architect: build a Workflow Automator that connects my tools", "description": "Tool pipeline automation", "icon": "🏗️"},
            {"label": "Community Agent", "value": "Agent Architect: build a Community Agent for Rabbit", "description": "Community auto-posts", "icon": "🏗️"},
            {"label": "My own idea", "value": "Agent Architect: I have a specific idea —", "description": "Describe what you need", "icon": "✏️"},
        ]

    return {
        "success": True,
        "action": "open_agents_panel",
        "panel_url": PANEL_URL,
        "intent": "BRAINSTORM",
        "operation": "brainstorm",
        "summary": "\n".join(lines),
        "present_options": {
            "_type": "present_options",
            "title": "Pick one to build, or describe your own",
            "options": options[:4],
            "allow_custom": True,
        },
    }


# ═══════════════════════════════════════════════════════════════
# HANDLER: REVIEW
# ═══════════════════════════════════════════════════════════════

def _handle_review(agents: list[dict]) -> dict:
    """Show workspace snapshot."""
    if not agents:
        return {
            "success": True,
            "action": "open_agents_panel",
            "panel_url": PANEL_URL,
            "intent": "REVIEW",
            "operation": "review",
            "summary": "**Workspace Overview**\n\nNo agents yet. I can design and build one — just describe what you need.",
            "present_options": {
                "_type": "present_options",
                "title": "Get started",
                "options": [
                    {"label": "Build an agent", "value": "Agent Architect: help me build my first agent", "description": "Tell me what you need automated", "icon": "🏗️"},
                    {"label": "Explore ideas", "value": "Agent Architect: what kinds of agents can you build?", "description": "See what's possible", "icon": "💡"},
                ],
                "allow_custom": True,
            },
        }

    lines = [f"**Workspace Overview — {len(agents)} agents**\n"]
    for a in agents[:15]:
        status = "🟢 Active" if a.get("is_active") else "🔴 Inactive"
        tools_str = ", ".join(a.get("tools", [])[:4])
        if len(a.get("tools", [])) > 4:
            tools_str += f" +{len(a['tools']) - 4} more"
        lines.append(f"- **{a['name']}** — {status} | {a.get('model', '?')} | Tools: {tools_str}")

    options = [
        {"label": f"Run {agents[0]['name']}", "value": f"Agent Architect: run {agents[0]['name']} now", "description": "Start immediate execution", "icon": "▶️"},
        {"label": "Build new agent", "value": "Agent Architect: build a new agent", "description": "Create something new", "icon": "🏗️"},
    ]
    if len(agents) > 3:
        options.append({"label": "Optimize agents", "value": "Agent Architect: review and suggest optimizations", "description": "Reduce costs or improve", "icon": "⚡"})
    else:
        options.append({"label": "Modify an agent", "value": f"Agent Architect: modify {agents[0]['name']}", "description": "Change config or tools", "icon": "✏️"})

    return {
        "success": True,
        "action": "open_agents_panel",
        "panel_url": PANEL_URL,
        "intent": "REVIEW",
        "operation": "review",
        "agent_count": len(agents),
        "summary": "\n".join(lines),
        "present_options": {
            "_type": "present_options",
            "title": "What would you like to do?",
            "options": options,
            "allow_custom": True,
        },
    }


# ═══════════════════════════════════════════════════════════════
# HANDLER: RUN
# ═══════════════════════════════════════════════════════════════

async def _handle_run(message: str, agents: list[dict], headers: dict[str, str]) -> dict:
    """Execute an existing agent."""
    if not agents:
        return {
            "success": True, "intent": "RUN", "operation": "run",
            "summary": "No agents to run yet.",
            "present_options": {"_type": "present_options", "title": "Get started", "options": [
                {"label": "Build an agent", "value": "Agent Architect: help me build my first agent", "description": "Create your first agent", "icon": "🏗️"},
            ], "allow_custom": True},
        }

    target = _find_agent(message, agents)
    if not target:
        if len(agents) == 1:
            target = agents[0]
        else:
            return {
                "success": True, "intent": "RUN", "operation": "run",
                "summary": "**Which agent would you like to run?**",
                "present_options": {"_type": "present_options", "title": "Select an agent", "options": [
                    {"label": f"{'🟢' if a.get('is_active') else '🔴'} {a['name']}", "value": f"Agent Architect: run {a['name']} now", "description": a.get("model", "?"), "icon": "▶️"}
                    for a in agents[:4]
                ], "allow_custom": True},
            }

    agent_id = target["id"]
    agent_name = target.get("name", "Agent")
    task = target.get("description") or target.get("system_prompt", "")[:200] or f"Run {agent_name}"

    result = await run_agent_full(agent_id, agent_name, task, headers)
    status = result.get("status", "unknown")
    emoji = {"completed": "✅", "running": "🔄", "failed": "❌", "launch_failed": "⚠️"}.get(status, "🔄")

    summary = f"**{emoji} {agent_name}** — {status}\n\nAgent ID: `{agent_id}`\n"
    if result.get("steps"):
        summary += f"Steps: {result['steps']}\n"
    if result.get("output"):
        summary += f"\n**Result:**\n{str(result['output'])[:500]}\n"
    if result.get("error"):
        summary += f"\n**Error:** {str(result['error'])[:200]}\n"
    if status == "running":
        summary += "\nStill running — check back in a moment."

    options = []
    if status == "completed":
        options = [
            {"label": "Run again", "value": f"Agent Architect: run {agent_name} now", "description": "Execute another run", "icon": "▶️"},
            {"label": "Set up schedule", "value": f"Agent Architect: schedule {agent_name} daily", "description": "Automate recurring", "icon": "⏰"},
        ]
    elif status == "failed":
        options = [
            {"label": "Diagnose", "value": f"Agent Architect: diagnose {agent_name}", "description": "Investigate failure", "icon": "🔧"},
            {"label": "Try again", "value": f"Agent Architect: run {agent_name} now", "description": "Retry execution", "icon": "🔄"},
        ]
    else:
        options = [{"label": "Check status", "value": f"Agent Architect: what's the status of {agent_name}?", "description": "See if run completed", "icon": "🔍"}]
    options.append({"label": "Build another", "value": "Agent Architect: build another agent", "description": "Create something new", "icon": "🏗️"})

    return {
        "success": True,
        "action": "open_agents_panel",
        "panel_url": PANEL_URL,
        "intent": "RUN",
        "operation": "run",
        "run_status": status,
        "summary": summary,
        "present_options": {"_type": "present_options", "title": "What's next?", "options": options[:4], "allow_custom": True},
    }


# ═══════════════════════════════════════════════════════════════
# HANDLER: SCHEDULE
# ═══════════════════════════════════════════════════════════════

async def _handle_schedule(message: str, agents: list[dict], headers: dict[str, str]) -> dict:
    """Create automated recurring runs."""
    if not agents:
        return {
            "success": True, "intent": "SCHEDULE", "operation": "schedule",
            "summary": "No agents to schedule yet.",
            "present_options": {"_type": "present_options", "title": "Get started", "options": [
                {"label": "Build an agent", "value": "Agent Architect: help me build my first agent", "icon": "🏗️", "description": "Create first"},
            ], "allow_custom": True},
        }

    target = _find_agent(message, agents)
    if not target:
        if len(agents) == 1:
            target = agents[0]
        else:
            return {
                "success": True, "intent": "SCHEDULE", "operation": "schedule",
                "summary": "**Which agent to schedule?**",
                "present_options": {"_type": "present_options", "title": "Select agent", "options": [
                    {"label": a["name"], "value": f"Agent Architect: schedule {a['name']} daily", "description": a.get("model", "?"), "icon": "⏰"}
                    for a in agents[:4]
                ], "allow_custom": True},
            }

    agent_id = target["id"]
    agent_name = target.get("name", "Agent")
    interval, cron, label = parse_schedule_from_message(message)
    goal = f"Automated {label} execution"

    ok = await create_schedule(agent_id, agent_name, interval, cron, goal, headers)
    if ok:
        return {
            "success": True, "action": "open_agents_panel", "panel_url": PANEL_URL,
            "intent": "SCHEDULE", "operation": "schedule",
            "summary": f"⏰ **Schedule created for {agent_name}!**\n\nFrequency: **{label}**\nAgent ID: `{agent_id}`\n\nIt will now run automatically.",
            "present_options": {"_type": "present_options", "title": "What's next?", "options": [
                {"label": f"Run {agent_name} now", "value": f"Agent Architect: run {agent_name} now", "description": "Don't wait — start now", "icon": "▶️"},
                {"label": "Build another", "value": "Agent Architect: build another agent", "description": "Create something new", "icon": "🏗️"},
                {"label": "Review all agents", "value": "Agent Architect: show me all my agents", "description": "See workspace", "icon": "📋"},
            ], "allow_custom": True},
        }
    return {
        "success": False, "action": "open_agents_panel", "panel_url": PANEL_URL,
        "intent": "SCHEDULE", "operation": "schedule",
        "summary": f"❌ Failed to create schedule for **{agent_name}**.",
        "present_options": {"_type": "present_options", "title": "Options", "options": [
            {"label": "Try again", "value": f"Agent Architect: schedule {agent_name} daily", "description": "Retry", "icon": "🔄"},
        ], "allow_custom": True},
    }


# ═══════════════════════════════════════════════════════════════
# HANDLER: MODIFY
# ═══════════════════════════════════════════════════════════════

async def _handle_modify(
    message: str, agents: list[dict], headers: dict[str, str], user_api_keys: dict | None,
) -> dict:
    """Modify an existing agent config via LLM delta analysis."""
    if not agents:
        return {
            "success": True, "intent": "MODIFY", "operation": "modify",
            "summary": "No agents to modify yet.",
            "present_options": {"_type": "present_options", "title": "Get started", "options": [
                {"label": "Build an agent", "value": "Agent Architect: build me an agent", "icon": "🏗️", "description": "Create first"},
            ], "allow_custom": True},
        }

    target = _find_agent(message, agents)
    if not target:
        if len(agents) == 1:
            target = agents[0]
        else:
            return {
                "success": True, "action": "open_agents_panel", "panel_url": PANEL_URL,
                "intent": "MODIFY", "operation": "modify",
                "summary": "**Which agent to modify?**",
                "present_options": {"_type": "present_options", "title": "Select agent", "options": [
                    {"label": a["name"], "value": f"Agent Architect: modify {a['name']}", "description": f"{a.get('model', '?')} · {len(a.get('tools', []))} tools", "icon": "✏️"}
                    for a in agents[:4]
                ], "allow_custom": True},
            }

    agent_id = target["id"]
    agent_name = target.get("name", "Agent")

    patch_data = await generate_modification(message, target, user_api_keys)
    if patch_data and patch_data.get("changes"):
        changes = patch_data["changes"]
        ok = await apply_modification(agent_id, changes, headers)
        if ok:
            change_summary = ", ".join(
                f"**{k}** → `{v}`" if not isinstance(v, list) else f"**{k}** → {len(v)} items"
                for k, v in changes.items()
            )
            return {
                "success": True, "action": "open_agents_panel", "panel_url": PANEL_URL,
                "intent": "MODIFY", "operation": "modify",
                "summary": f"✅ **{agent_name}** modified\n\n**Changes:** {change_summary}\n*{patch_data.get('explanation', '')}*",
                "present_options": {"_type": "present_options", "title": "What's next?", "options": [
                    {"label": f"Run {agent_name}", "value": f"Agent Architect: run {agent_name} now", "description": "Test changes", "icon": "▶️"},
                    {"label": "More changes", "value": f"Agent Architect: modify {agent_name}", "description": "Continue modifying", "icon": "✏️"},
                    {"label": "Review agents", "value": "Agent Architect: show me all my agents", "description": "See workspace", "icon": "📋"},
                ], "allow_custom": True},
            }

    # Fallback: show current config
    return {
        "success": True, "action": "open_agents_panel", "panel_url": PANEL_URL,
        "intent": "MODIFY", "operation": "modify",
        "summary": (
            f"**Modifying: {agent_name}**\n\n"
            f"Current: {target.get('model', '?')} | Tools: {', '.join(target.get('tools', [])[:5])}\n\n"
            "Tell me what to change — e.g.:\n"
            "• \"add web_search and fetch_url tools\"\n"
            "• \"switch to gpt-4o\"\n"
            "• \"change the goal to focus on X\""
        ),
        "present_options": {"_type": "present_options", "title": "Common changes", "options": [
            {"label": "Add tools", "value": f"Agent Architect: add web_search and fetch_url to {agent_name}", "description": "Expand capabilities", "icon": "🔧"},
            {"label": "Change model", "value": f"Agent Architect: switch {agent_name} to gpt-4o", "description": "Upgrade intelligence", "icon": "🧠"},
            {"label": "Update goal", "value": f"Agent Architect: update goal for {agent_name}", "description": "Refine purpose", "icon": "🎯"},
        ], "allow_custom": True},
    }


# ═══════════════════════════════════════════════════════════════
# HANDLER: DIAGNOSE
# ═══════════════════════════════════════════════════════════════

async def _handle_diagnose(message: str, agents: list[dict], headers: dict[str, str]) -> dict:
    """Investigate agent failures."""
    if not agents:
        return {"success": True, "intent": "DIAGNOSE", "operation": "diagnose", "summary": "No agents to diagnose."}

    target = _find_agent(message, agents) or agents[0]
    agent_id = target["id"]
    agent_name = target.get("name", "?")

    lines = [f"**Diagnosing: {agent_name}** (`{agent_id}`)\n"]
    sessions = await fetch_agent_sessions(agent_id, headers)
    if sessions:
        for s in sessions[:5]:
            emoji = {"completed": "✅", "failed": "❌", "running": "🔄", "cancelled": "⏹️"}.get(s.get("status", ""), "❓")
            lines.append(
                f"- {emoji} Session `{str(s.get('id', '?'))[:8]}...` — {s.get('status', '?')} "
                f"| Goal: {(s.get('current_goal') or 'none')[:60]} | Loops: {s.get('loop_count', 0)}"
            )
            if s.get("error_message"):
                lines.append(f"  Error: {s['error_message'][:120]}")
    else:
        lines.append("No sessions found.")

    return {
        "success": True, "action": "open_agents_panel", "panel_url": PANEL_URL,
        "intent": "DIAGNOSE", "operation": "diagnose",
        "summary": "\n".join(lines),
        "present_options": {"_type": "present_options", "title": "What to do?", "options": [
            {"label": "Fix with rebuild", "value": f"Agent Architect: modify {agent_name} to fix issues", "description": "Change agent config", "icon": "🔧"},
            {"label": "Run again", "value": f"Agent Architect: run {agent_name} now", "description": "Retry execution", "icon": "▶️"},
            {"label": "Build replacement", "value": "Agent Architect: build a replacement agent", "description": "Start fresh", "icon": "🏗️"},
        ], "allow_custom": True},
    }


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _find_agent(message: str, agents: list[dict]) -> dict | None:
    """Find agent by name in user message. Fuzzy matching."""
    msg = re.sub(r"^agent\s*architect\s*:\s*", "", message.lower().strip())
    # Exact name match
    for a in agents:
        if a.get("name", "").lower() in msg:
            return a
    # Word match
    for a in agents:
        words = a.get("name", "").lower().replace("_", " ").split()
        if any(w in msg for w in words if len(w) > 3):
            return a
    return None


def _build_options(created: list[dict], existing: list[dict]) -> dict:
    """Build follow-up options after agent creation."""
    options = []
    if created:
        first = created[0].get("name", "agent")
        options.append({"label": f"Run {first}", "value": f"Agent Architect: run {first} now", "description": "Start test run", "icon": "▶️"})
        options.append({"label": "Schedule it", "value": f"Agent Architect: schedule {first} daily", "description": "Automate", "icon": "⏰"})
    options.append({"label": "Build another", "value": "Agent Architect: build another agent", "description": "Create more", "icon": "➕"})
    return {
        "_type": "present_options",
        "title": "What's next?",
        "options": options[:4],
        "allow_custom": True,
    }
