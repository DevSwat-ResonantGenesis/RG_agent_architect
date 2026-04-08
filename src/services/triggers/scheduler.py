"""Trigger/Scheduler — Time-based (minute/hour/day/week) + webhooks"""
from typing import Dict

async def set_schedule(agent_id: str, interval: str = "daily", timezone: str = "UTC") -> Dict:
    return {"agent_id": agent_id, "interval": interval, "timezone": timezone, "status": "scheduled"}

async def remove_schedule(agent_id: str) -> Dict:
    return {"agent_id": agent_id, "status": "removed"}
