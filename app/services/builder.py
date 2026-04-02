"""
RG Agent Architect — Builder Service
Blueprint generation, agent creation, modification, system prompt building.
"""
import json
import logging
import re

import httpx

from ..config import settings
from .llm_client import llm_json, llm_call
from .prompts import (
    PLANNING_PROMPT,
    BRAINSTORM_PROMPT,
    MODIFY_PROMPT,
    build_system_prompt,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# BLUEPRINT GENERATION
# ═══════════════════════════════════════════════════════════════

async def generate_blueprint(
    message: str,
    user_api_keys: dict | None = None,
    platform_context: str = "Resonant Genesis — 160+ tools",
    existing_agents: str = "None yet",
) -> dict | None:
    """Use LLM to produce a structured agent blueprint JSON."""
    filled = PLANNING_PROMPT.format(
        platform_context=platform_context,
        existing_agents=existing_agents,
    )
    prompt = f"{filled}\n\nUSER REQUEST: {message}\n\nProduce the JSON blueprint now:"
    system = build_system_prompt()

    return await llm_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=2000,
        user_api_keys=user_api_keys,
        timeout=25.0,
    )


# ═══════════════════════════════════════════════════════════════
# BRAINSTORM — opinionated proposals
# ═══════════════════════════════════════════════════════════════

async def generate_brainstorm(
    message: str,
    memory_facts: str,
    agent_summary: str,
    tools_summary: str,
    user_api_keys: dict | None = None,
) -> dict | None:
    """Generate 3 opinionated agent proposals based on user context."""
    prompt = BRAINSTORM_PROMPT.format(
        memory_facts=memory_facts or "No saved context yet",
        agent_summary=agent_summary or "Fresh workspace — no agents yet",
        tools_summary=tools_summary or "160+ tools available",
        message=message[:500],
    )
    return await llm_json(
        [{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=800,
        user_api_keys=user_api_keys,
        timeout=15.0,
    )


# ═══════════════════════════════════════════════════════════════
# AGENT CREATION — talk to Agent Engine
# ═══════════════════════════════════════════════════════════════

def build_agent_system_prompt(name: str, hint: str, tools: list[str]) -> str:
    """Build a production system prompt for an autonomous agent."""
    tools_str = ", ".join(tools[:15]) if tools else "general"
    return (
        f"You are {name}, an autonomous AI agent on the Resonant Genesis platform.\n\n"
        f"Your role: {hint}\n\n"
        f"Available tools: {tools_str}\n\n"
        "Rules:\n"
        "- Execute your goal systematically. Break complex goals into steps.\n"
        "- Use tools when they help. Prefer built-in tools over workarounds.\n"
        "- Store important findings in memory for future runs.\n"
        "- If a step fails, try an alternative approach before reporting failure.\n"
        "- Be thorough but efficient — minimize unnecessary API calls.\n"
        "- Always produce a clear summary of what you accomplished."
    )


def build_safety_config(tools: list[str], mode: str = "governed") -> dict:
    """Build safety configuration based on tools and mode."""
    config = {
        "max_tool_calls": 50,
        "max_loops": 25,
        "timeout_seconds": 300,
        "allow_external_requests": any(
            t in tools for t in ("external_http_request", "fetch_url", "read_webpage")
        ),
        "allow_code_execution": "execute_code" in tools,
        "blocked_actions": ["delete_community", "delete_user", "admin_override"],
    }
    if mode == "unbounded":
        config["max_tool_calls"] = 200
        config["max_loops"] = 100
        config["timeout_seconds"] = 900
    elif mode == "supervised":
        config["max_tool_calls"] = 100
        config["max_loops"] = 50
        config["timeout_seconds"] = 600
    return config


async def create_single_agent(
    client: httpx.AsyncClient,
    payload: dict,
    headers: dict[str, str],
) -> dict | None:
    """Create a single agent via the Agent Engine API."""
    try:
        resp = await client.post(
            f"{settings.AGENT_ENGINE_URL}/agents/",
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        logger.warning(f"[BUILDER] Agent creation failed: HTTP {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        logger.error(f"[BUILDER] Agent creation error: {e}")
    return None


async def create_agents_from_blueprint(
    blueprint: dict,
    user_id: str,
    headers: dict[str, str],
) -> tuple[list[dict], list[str]]:
    """Create all agents from a blueprint. Returns (created_agents, detail_lines)."""
    agent_blueprints = blueprint.get("agents", [])
    created: list[dict] = []
    details: list[str] = []

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for i, bp in enumerate(agent_blueprints):
            name = bp.get("name", f"Agent {i + 1}")
            desc = bp.get("description", "Created by Agent Architect")
            tools = bp.get("tools", ["web_search", "fetch_url"])
            provider = bp.get("provider", "groq")
            model = bp.get("model", "llama-3.3-70b-versatile")
            temp = bp.get("temperature", 0.6)
            max_tokens = bp.get("max_tokens", 4096)
            mode = bp.get("mode", "governed")
            hint = bp.get("system_prompt_hint", desc)

            system_prompt = build_agent_system_prompt(name, hint, tools)
            safety = build_safety_config(tools, mode)

            payload = {
                "name": name,
                "description": desc,
                "system_prompt": system_prompt,
                "provider": provider,
                "model": model,
                "temperature": temp,
                "max_tokens": max_tokens,
                "tools": tools,
                "mode": mode,
                "safety_config": safety,
                "allowed_actions": tools,
                "blocked_actions": ["delete_community", "delete_user", "admin_override"],
            }

            result = await create_single_agent(client, payload, headers)
            if not result:
                details.append(f"❌ **{name}** — creation failed")
                continue

            agent_id = result.get("id")
            created.append(result)
            lines = [f"✅ **{name}** — `{agent_id}`"]

            # Assign goal
            goal_text = bp.get("goal")
            if goal_text and agent_id:
                try:
                    goal_resp = await client.post(
                        f"{settings.AGENT_ENGINE_URL}/agents/goals/{agent_id}/assign",
                        headers=headers,
                        json={"description": goal_text, "priority": bp.get("goal_priority", 5)},
                    )
                    if goal_resp.status_code in (200, 201):
                        lines.append(f"   🎯 {goal_text[:80]}")
                    else:
                        lines.append(f"   ⚠️ Goal: status {goal_resp.status_code}")
                except Exception as e:
                    logger.warning(f"[BUILDER] Goal assign failed for {name}: {e}")

            # Create schedule
            schedule = bp.get("schedule")
            if schedule and not isinstance(schedule, dict):
                schedule = {"interval_seconds": 21600}
            if schedule and agent_id:
                try:
                    sched_payload = {
                        "name": schedule.get("name", f"{name} Schedule"),
                        "goal": schedule.get("goal", goal_text or desc),
                    }
                    if schedule.get("cron_expression"):
                        sched_payload["cron_expression"] = schedule["cron_expression"]
                    elif schedule.get("interval_seconds"):
                        sched_payload["interval_seconds"] = schedule["interval_seconds"]
                    else:
                        sched_payload["interval_seconds"] = 21600

                    sched_resp = await client.post(
                        f"{settings.AGENT_ENGINE_URL}/agents/{agent_id}/schedules",
                        headers=headers,
                        json=sched_payload,
                    )
                    if sched_resp.status_code in (200, 201):
                        cron_str = sched_payload.get("cron_expression") or f"every {sched_payload.get('interval_seconds', '?')}s"
                        lines.append(f"   ⏰ {cron_str}")
                except Exception as e:
                    logger.warning(f"[BUILDER] Schedule creation failed for {name}: {e}")

            # Webhook
            if bp.get("webhook", False) and agent_id:
                try:
                    wh_resp = await client.post(
                        f"{settings.AGENT_ENGINE_URL}/webhooks/agent/{agent_id}/create",
                        headers=headers,
                        json={"name": f"Webhook for {name}"},
                    )
                    if wh_resp.status_code in (200, 201):
                        wh_data = wh_resp.json()
                        result["webhook_url"] = wh_data.get("webhook_url", "")
                        lines.append(f"   🔗 Webhook: `{result['webhook_url']}`")
                except Exception as e:
                    logger.warning(f"[BUILDER] Webhook failed for {name}: {e}")

            # Autonomy mode
            autonomy = bp.get("autonomy_mode", "governed")
            if autonomy != "governed" and agent_id:
                try:
                    await client.post(
                        f"{settings.AGENT_ENGINE_URL}/autonomy/mode/{agent_id}",
                        headers=headers,
                        json={"mode": autonomy, "reason": "Set by Agent Architect"},
                    )
                except Exception:
                    pass

            details.append("\n".join(lines))

    return created, details


# ═══════════════════════════════════════════════════════════════
# AGENT MODIFICATION
# ═══════════════════════════════════════════════════════════════

async def generate_modification(
    message: str,
    agent: dict,
    user_api_keys: dict | None = None,
) -> dict | None:
    """Use LLM to determine what changes to make to an agent."""
    prompt = MODIFY_PROMPT.format(
        agent_name=agent.get("name", "?"),
        agent_model=agent.get("model", "llama-3.3-70b-versatile"),
        agent_provider=agent.get("provider", "groq"),
        agent_tools=agent.get("tools", []),
        agent_mode=agent.get("mode", "governed"),
        agent_active=agent.get("is_active", False),
        message=message,
    )
    return await llm_json(
        [{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=500,
        user_api_keys=user_api_keys,
        timeout=12.0,
    )


async def apply_modification(
    agent_id: str,
    changes: dict,
    headers: dict[str, str],
) -> bool:
    """Apply a set of changes to an agent via PATCH."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.patch(
                f"{settings.AGENT_ENGINE_URL}/agents/{agent_id}",
                headers={**headers, "Content-Type": "application/json"},
                json=changes,
            )
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"[BUILDER] Modify PATCH failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# SIMPLE FALLBACK BUILDER
# ═══════════════════════════════════════════════════════════════

def build_simple_payload(message: str) -> dict:
    """Create a minimal agent payload when LLM planning fails."""
    clean = re.sub(r"(?i)^agent\s*architect\s*:\s*", "", message).strip()
    name_words = clean.split()[:4]
    name = " ".join(w.capitalize() for w in name_words) + " Agent"
    return {
        "name": name[:60],
        "description": clean[:200],
        "system_prompt": build_agent_system_prompt(name, clean[:200], ["web_search", "fetch_url", "memory_write"]),
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.6,
        "max_tokens": 4096,
        "tools": ["web_search", "fetch_url", "memory_write"],
        "mode": "governed",
        "safety_config": build_safety_config(["web_search", "fetch_url", "memory_write"]),
    }
