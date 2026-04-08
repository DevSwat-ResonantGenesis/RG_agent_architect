"""Billing Client — Credits, deductions, economic state via billing_service"""
import logging
from typing import Dict

import httpx

logger = logging.getLogger(__name__)

BILLING_URL = "http://billing_service:8000"


async def get_economic_state(user_id: str) -> Dict:
    """Get user's full economic state (credits, plan, limits)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{BILLING_URL}/economic-state/{user_id}")
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f"[Billing] get state failed: {e}")
    return {"credits_remaining": 0, "plan": "free"}


async def check_credits(user_id: str) -> Dict:
    """Check if user has sufficient credits for a run."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{BILLING_URL}/economic-state/{user_id}/check-credits")
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f"[Billing] check credits failed: {e}")
    return {"has_credits": True}


async def deduct_credits(user_id: str, amount: int = 1, reason: str = "agent_run") -> Dict:
    """Deduct credits after a run."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{BILLING_URL}/economic-state/{user_id}/deduct",
                             json={"amount": amount, "reason": reason})
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f"[Billing] deduct failed: {e}")
    return {"deducted": False}
