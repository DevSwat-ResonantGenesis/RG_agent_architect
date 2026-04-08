"""Trigger/Scheduler — APScheduler for time-based agent runs"""
import logging
from typing import Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler = None

INTERVAL_MAP = {
    "minutely": {"minutes": 1}, "hourly": {"hours": 1},
    "daily": {"days": 1}, "weekly": {"weeks": 1},
}


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
        _scheduler.start()
        logger.info("[Scheduler] Started")
    return _scheduler


async def _run_scheduled_agent(workspace_id: str, agent_id: str):
    from src.runner.runner import Runner
    logger.info(f"[Scheduler] Triggered run for agent {agent_id}")
    result = await Runner(workspace_id).run(agent_id)
    logger.info(f"[Scheduler] Agent {agent_id} result: {result.get('outcome')}")


async def set_schedule(workspace_id: str, agent_id: str, interval: str = "daily", timezone: str = "UTC") -> Dict:
    sched = get_scheduler()
    job_id = f"agent_{agent_id}"
    params = INTERVAL_MAP.get(interval, {"days": 1})
    sched.add_job(_run_scheduled_agent, IntervalTrigger(**params, timezone=timezone),
                  args=[workspace_id, agent_id], id=job_id, replace_existing=True)
    logger.info(f"[Scheduler] Set {interval} schedule for agent {agent_id}")
    return {"agent_id": agent_id, "interval": interval, "timezone": timezone, "status": "scheduled"}


async def remove_schedule(agent_id: str) -> Dict:
    sched = get_scheduler()
    job_id = f"agent_{agent_id}"
    if sched.get_job(job_id):
        sched.remove_job(job_id)
    return {"agent_id": agent_id, "status": "removed"}
