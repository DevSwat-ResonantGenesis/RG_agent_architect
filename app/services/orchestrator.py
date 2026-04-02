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
    GOAL_CRAFTING_PROMPT,
    USER_FACTS_PROMPT,
    build_system_prompt,
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
    """Twin-level orchestration entry point.

    Flow:
    1. Fetch workspace context (agents, tools, memory) — 3 parallel calls
    2. Extract and store user facts from message (memory management)
    3. Check if this is a confirmation of a prior plan
    4. Classify intent
    5. Route to appropriate handler
    6. ALWAYS return structured response with follow-up options
    """
    logger.info(f"🏗️ [ORCHESTRATE] Message: {message[:120]!r}")

    # Step 0: Context Protocol — gather workspace state (Twin: 3 parallel calls)
    workspace = await fetch_workspace_context(user_id, headers)
    agents = workspace.get("agents", [])
    agent_count = len(agents)

    logger.info(f"🏗️ [ORCHESTRATE] Context: {agent_count} agents, tools={workspace.get('tools_summary')}")

    # Step 0.5: Memory management — extract and store user facts
    await _extract_and_store_user_facts(message, user_id, workspace.get("memory_facts", ""), user_api_keys)

    # Step 1: Check confirmation
    if _is_confirmation(message, context):
        original = _extract_original_request(context)
        # Retrieve crafted goal metadata from context if available
        crafted_meta = context.get("crafted_goal_meta")
        logger.info(f"🏗️ [ORCHESTRATE] Confirmation → build: {original[:100]!r}")
        return await _handle_build_execute(
            original, user_id, headers, user_api_keys, workspace, agents,
            crafted_meta=crafted_meta,
        )

    # Step 2: Classify intent
    intent = await _classify_intent(message, user_api_keys)
    logger.info(f"🏗️ [ORCHESTRATE] Intent: {intent}")

    # Step 3: Route by intent
    if intent == "BRAINSTORM":
        return await _handle_brainstorm(message, user_id, agents, workspace, user_api_keys)
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

    # BUILD intent: Phase 1 — goal crafting + plan preview
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
# TWIN-LEVEL: GOAL CRAFTING PIPELINE (8 steps)
# ═══════════════════════════════════════════════════════════════

async def _craft_goal(
    message: str,
    workspace: dict,
    agents: list[dict],
    user_api_keys: dict | None = None,
) -> dict | None:
    """Twin's 8-step goal crafting pipeline via LLM.

    Returns dict with: crafted_goal, agent_name, tools_needed, schedule,
    scope_risk, assumptions, auth_needed, auth_warning, reasoning, etc.
    """
    memory_facts = workspace.get("memory_facts", "No saved context yet")
    tools_summary = workspace.get("tools_summary", "160+ tools available")
    agents_str = "Fresh workspace — no agents yet."
    if agents:
        descs = [f"- {a['name']} ({a.get('model', '?')}, tools: {', '.join(a.get('tools', [])[:4])})" for a in agents[:10]]
        agents_str = "\n".join(descs)

    prompt = GOAL_CRAFTING_PROMPT.format(
        message=message[:500],
        memory_facts=memory_facts or "No saved context yet",
        existing_agents=agents_str,
        tools_summary=tools_summary,
    )
    system = build_system_prompt()

    result = await llm_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=1500,
        user_api_keys=user_api_keys,
        timeout=20.0,
    )

    if result and result.get("crafted_goal"):
        logger.info(f"🎯 [GOAL] Crafted: {result['crafted_goal'][:100]}")
        return result

    logger.warning("[GOAL] Goal crafting failed, falling back to raw message")
    return None


# ═══════════════════════════════════════════════════════════════
# TWIN-LEVEL: MEMORY MANAGEMENT
# ═══════════════════════════════════════════════════════════════

async def _extract_and_store_user_facts(
    message: str,
    user_id: str,
    existing_memory: str,
    user_api_keys: dict | None = None,
) -> None:
    """Twin-style: extract user facts from message and store in memory.

    Runs in background — never blocks the main flow. Stores facts like
    name, role, company, industry, location, preferences.
    """
    # Skip short messages or commands
    msg_clean = re.sub(r"^agent\s*architect\s*:\s*", "", message.lower().strip())
    if len(msg_clean) < 15 or msg_clean in ("yes", "no", "yes, build it", "go ahead", "build it"):
        return

    try:
        prompt = USER_FACTS_PROMPT.format(
            message=message[:300],
            memory_facts=existing_memory or "No existing memory",
        )
        result = await llm_json(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200,
            user_api_keys=user_api_keys,
            timeout=8.0,
        )
        if result and result.get("facts"):
            for fact in result["facts"][:5]:
                sentence = fact.get("sentence") or f"User {fact.get('key', '?')}: {fact.get('value', '?')}"
                await store_memory(
                    user_id,
                    sentence,
                    {"type": "user_fact", "key": fact.get("key"), "value": fact.get("value")},
                )
                logger.info(f"🧠 [MEMORY] Stored: {sentence[:80]}")
    except Exception as e:
        logger.debug(f"[MEMORY] Facts extraction failed (non-critical): {e}")


# ═══════════════════════════════════════════════════════════════
# HANDLER: BUILD PREVIEW (Phase 1 — Twin Goal Crafting)
# ═══════════════════════════════════════════════════════════════

async def _handle_build_preview(
    message: str,
    user_id: str,
    headers: dict[str, str],
    user_api_keys: dict | None,
    workspace: dict,
    agents: list[dict],
) -> dict:
    """Phase 1 — Twin Goal Crafting Pipeline.

    1. Run 8-step goal crafting via LLM
    2. Present refined goal in blockquote
    3. Show assumptions, auth warnings, scope risk
    4. Wait for confirmation before building
    """
    # Step 1: Craft goal using Twin's 8-step pipeline
    crafted = await _craft_goal(message, workspace, agents, user_api_keys)

    if not crafted:
        # Goal crafting failed — fall back to direct blueprint + build
        return await _handle_build_execute(message, user_id, headers, user_api_keys, workspace, agents)

    agent_name = crafted.get("agent_name", "Agent")
    crafted_goal = crafted.get("crafted_goal", message)
    description = crafted.get("description", "")
    tools_needed = crafted.get("tools_needed", [])
    reasoning = crafted.get("reasoning", "")
    assumptions = crafted.get("assumptions", [])
    schedule = crafted.get("schedule")
    schedule_label = crafted.get("schedule_label")
    scope_risk = crafted.get("scope_risk", "safe")
    scope_risk_reason = crafted.get("scope_risk_reason")
    scope_risk_scale = crafted.get("scope_risk_scale")
    auth_needed = crafted.get("auth_needed", [])
    auth_warning = crafted.get("auth_warning")
    model = crafted.get("model", "llama-3.3-70b-versatile")
    provider = crafted.get("provider", "groq")

    # Also check regex-based scope risk
    regex_risk = _assess_scope_risk(message)
    if regex_risk["level"] == "high" and scope_risk == "safe":
        scope_risk = "high"
        scope_risk_reason = regex_risk["reason"]

    # Step 2: Build the goal presentation (Twin-style blockquote)
    summary = f"**{agent_name}**\n\n"
    if reasoning:
        summary += f"*{reasoning}*\n\n"

    summary += f"> {crafted_goal}\n\n"

    summary += f"**Model:** `{provider}/{model}`\n"
    summary += f"**Tools:** {', '.join(tools_needed[:8])}\n"
    if schedule_label:
        summary += f"**Schedule:** {schedule_label} (will be set automatically after build)\n"
    summary += "\n"

    # Auth warnings — Twin always warns about needed integrations
    if auth_needed:
        services_str = ", ".join(auth_needed)
        summary += f"🔗 **Integrations needed:** {services_str}\n"
        if auth_warning:
            summary += f"   *{auth_warning}*\n"
        summary += "\n"

    # Assumptions — Twin always shows what it assumed
    if assumptions:
        summary += "**Assumptions:**\n"
        for a in assumptions[:6]:
            summary += f"- {a}\n"
        summary += "\n"

    # Step 3: Scope risk presentation (Twin-style)
    if scope_risk == "high":
        summary += f"⚠️ **Scope risk: HIGH** — {scope_risk_reason or 'Could expand into many operations'}\n"
        if scope_risk_scale:
            summary += f"*{scope_risk_scale} — this will be a long run with high credit usage.*\n"
        summary += "\n"
        options = [
            {"label": "Build small sample first", "value": "Agent Architect: build this but limit to 10 items as a test", "description": "Safe starting point", "icon": "🧪", "default": True},
            {"label": "Build full scope", "value": "Agent Architect: yes, build it", "description": "Full power — may be costly", "icon": "🚀"},
            {"label": "Adjust scope", "value": "Agent Architect: let me adjust — ", "description": "Change before building", "icon": "✏️"},
        ]
    elif scope_risk == "moderate":
        summary += f"⚠️ **Scope risk: moderate** — {scope_risk_reason or 'Multi-step processing that could scale up'}\n\n"
        options = [
            {"label": "Build with limits", "value": "Agent Architect: yes, build it", "description": "Safe default", "icon": "🛡️", "default": True},
            {"label": "Build unrestricted", "value": "Agent Architect: build with no restrictions", "description": "Full power", "icon": "⚡"},
            {"label": "Adjust", "value": "Agent Architect: let me adjust — ", "description": "Change before building", "icon": "✏️"},
        ]
    else:
        options = [
            {"label": "Build it", "value": "Agent Architect: yes, build it", "description": "Create this agent now", "icon": "🏗️"},
            {"label": "Adjust something", "value": "Agent Architect: let me adjust — ", "description": "Change before building", "icon": "✏️"},
        ]

    return {
        "success": True,
        "action": "open_agents_panel",
        "panel_url": PANEL_URL,
        "operation": "plan_preview",
        "intent": "BUILD",
        "scope_risk": scope_risk,
        "crafted_goal_meta": crafted,
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
    crafted_meta: dict | None = None,
) -> dict:
    """Phase 2 — Twin Build Execute.

    1. Use crafted goal metadata if available (from Phase 1)
    2. Generate full blueprint
    3. Create agents
    4. Proactively set schedule if recurrence was detected
    5. Execute first run + verify results
    6. Store build event in memory
    7. ALWAYS present follow-up options
    """
    import httpx as _httpx

    platform_ctx = f"Resonant Genesis ({workspace.get('tools_summary', '160+ tools')})"
    if workspace.get("memory_facts"):
        platform_ctx += f"\nUser info: {workspace['memory_facts'][:300]}"

    agents_str = "None yet"
    if agents:
        descs = [f"- {a['name']} ({a.get('model', '?')})" for a in agents[:10]]
        agents_str = "\n".join(descs)

    # If we have crafted goal metadata from Phase 1, use it to enrich the blueprint prompt
    build_message = message
    if crafted_meta and crafted_meta.get("crafted_goal"):
        build_message = crafted_meta["crafted_goal"]

    blueprint = await generate_blueprint(build_message, user_api_keys, platform_ctx, agents_str)

    if not blueprint or "agents" not in blueprint:
        # Ultimate fallback: simple builder
        payload = build_simple_payload(message)
        # If we have crafted metadata, override the simple payload with it
        if crafted_meta:
            payload["name"] = crafted_meta.get("agent_name", payload.get("name", "Agent"))
            payload["description"] = crafted_meta.get("description", payload.get("description", ""))
            if crafted_meta.get("tools_needed"):
                payload["tools"] = crafted_meta["tools_needed"]
            if crafted_meta.get("model"):
                payload["model"] = crafted_meta["model"]
            if crafted_meta.get("provider"):
                payload["provider"] = crafted_meta["provider"]

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

    # === Twin: Proactive schedule setting ===
    # If goal crafting detected recurrence, set trigger automatically
    schedule_set = False
    schedule_label = ""
    if crafted_meta and crafted_meta.get("schedule") and created:
        sched = crafted_meta["schedule"]
        schedule_label = crafted_meta.get("schedule_label", "recurring")
        interval = sched.get("interval_seconds", 86400)
        cron = sched.get("cron_expression")
        for agent in created:
            agent_id = agent.get("id")
            agent_name = agent.get("name", "Agent")
            if agent_id:
                goal = crafted_meta.get("crafted_goal", f"Automated {schedule_label} execution")
                ok = await create_schedule(agent_id, agent_name, interval, cron, goal, headers)
                if ok:
                    schedule_set = True
                    logger.info(f"⏰ [BUILD] Proactively set {schedule_label} schedule for {agent_name}")

    # Auto-execute first run
    exec_results = await run_agents_batch(created, bp_agents, headers)

    # Store build event in memory (Twin: always persist)
    if created:
        names = [c.get("name", "?") for c in created]
        mem_content = f"User built {len(created)} agent(s): {', '.join(names)}. Request: {message[:200]}"
        if schedule_set:
            mem_content += f" Schedule: {schedule_label}."
        await store_memory(
            user_id,
            mem_content,
            {"type": "build_event", "agent_count": len(created), "agent_names": names},
        )

    # Build summary
    n_created = len(created)
    n_total = len(bp_agents)

    summary = f"**{n_created}/{n_total} agents created**\n\n"
    if reasoning:
        summary += f"*{reasoning}*\n\n"
    summary += "---\n\n"
    summary += "\n\n".join(details)

    if team_name and n_created > 1:
        summary += f"\n\n**Team:** {team_name} ({team_workflow or 'sequential'} workflow)"

    # Proactive schedule notification (Twin-style)
    if schedule_set:
        summary += f"\n\n⏰ **Schedule set:** {schedule_label} — this agent will now run automatically."

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

    # === Twin: Follow-up options (ALWAYS present, context-aware) ===
    any_running = any(er.get("status") in ("running", "started") for er in exec_results)
    any_completed = any(er.get("status") == "completed" for er in exec_results)
    any_failed = any(er.get("status") in ("failed", "launch_failed") for er in exec_results)

    options = []
    if any_running and created:
        first = created[0]
        options.append({"label": f"Check status", "value": f"Agent Architect: what's the status of {first.get('name', 'agent')}?", "description": "See if run completed", "icon": "🔍"})
    if any_completed and not schedule_set:
        options.append({"label": "Set up schedule", "value": f"Agent Architect: schedule {created[0].get('name', 'agent')} daily", "description": "Automate recurring runs", "icon": "⏰"})
    if any_failed and created:
        options.append({"label": "Diagnose issues", "value": f"Agent Architect: diagnose {created[0].get('name', 'agent')}", "description": "Investigate what went wrong", "icon": "🔧"})
    if any_completed or any_running:
        options.append({"label": "Build another", "value": "Agent Architect: build another agent", "description": "Create something new", "icon": "➕"})
    if not options:
        options.append({"label": "Try again", "value": f"Agent Architect: {message[:80]}", "description": "Retry the build", "icon": "🔄"})
        options.append({"label": "Build something else", "value": "Agent Architect: build another agent", "description": "Start fresh", "icon": "➕"})

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
        "schedule_set": schedule_set,
        "schedule_label": schedule_label if schedule_set else None,
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
    user_id: str,
    agents: list[dict],
    workspace: dict,
    user_api_keys: dict | None,
) -> dict:
    """Twin-style brainstorm: opinionated, memory-aware, outcome-focused.

    Twin NEVER asks 'what do you want to build?' — it PROPOSES based on context.
    Paints vivid outcome pictures. Pushes toward outcomes, not tasks.
    """
    memory_facts = workspace.get("memory_facts", "")
    agent_summary = "Fresh workspace — no agents yet."
    if agents:
        names = [a.get("name", "?") for a in agents[:10]]
        agent_summary = f"{len(agents)} existing agents: {', '.join(names)}"

    proposals = await generate_brainstorm(
        message,
        memory_facts,
        agent_summary,
        workspace.get("tools_summary", "160+ tools"),
        user_api_keys,
    )

    if proposals and proposals.get("proposals"):
        intro = proposals.get("intro", "Here's what I'd build based on your situation.")
        items = proposals["proposals"][:3]

        # Twin-style: concise, opinionated, outcome-focused presentation
        lines = [f"**{intro}**\n"]
        if memory_facts:
            lines.append(f"*I know: {memory_facts[:150]}*\n")
        for i, p in enumerate(items):
            lines.append(f"**{i+1}. {p.get('name', 'Agent')}**")
            lines.append(f"   {p.get('description', '')}")
            if p.get("why"):
                lines.append(f"   *Why this matters:* {p['why']}")
            if p.get("outcome"):
                lines.append(f"   *Result:* {p['outcome']}")
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
        # Twin-style fallback: opinionated defaults based on available tools
        lines = [
            "**Here's what I'd build for you:**\n",
            "**1. Morning Briefing** — Collects top HackerNews stories and trending GitHub AI repos, compiles a digest, and sends it to your email every morning.",
            "**2. Workflow Automator** — Connects your tools (Drive, Calendar, GitHub, Slack) into automated pipelines that trigger on schedule or events.",
            "**3. Community Agent** — Monitors Rabbit communities for relevant posts, auto-responds with helpful content, and posts on a schedule.",
            "",
            "Each runs autonomously once built — no daily effort from you.",
            "",
        ]
        options = [
            {"label": "Morning Briefing", "value": "Agent Architect: build a Morning Briefing that collects top HackerNews stories and AI GitHub repos, then emails me a digest daily", "description": "Daily news digest via email", "icon": "🏗️"},
            {"label": "Workflow Automator", "value": "Agent Architect: build a Workflow Automator that connects my Drive, Calendar, and GitHub", "description": "Tool pipeline automation", "icon": "🏗️"},
            {"label": "Community Agent", "value": "Agent Architect: build a Community Agent that monitors and posts in Rabbit communities", "description": "Community auto-posts", "icon": "🏗️"},
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
