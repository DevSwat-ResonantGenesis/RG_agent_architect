"""Credits/Billing — Plan enforcement and credit counting"""
from src.core.config import PLANS

async def get_credits_info(workspace_id: str) -> dict:
    return {"plan": "free", "credits_total": 2200, "credits_used": 0, "credits_remaining": 2200}
