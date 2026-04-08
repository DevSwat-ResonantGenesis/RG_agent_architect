"""Apify Manager — 35+ scrapers: get_input_schema → run → status → result (MANDATORY)"""
import asyncio, httpx
from typing import Any, Dict, List
from src.core.config import APIFY_API_TOKEN

SCRAPER_CATALOG = {
    "linkedin_jobs": 80, "linkedin_profiles": 15, "indeed": 50,
    "instagram": 90, "tiktok": 50, "reddit": 300, "youtube": 260,
    "amazon": 15, "google_maps": 220, "zillow_zip_search": 60,
    "booking": 15, "facebook_ads": 300, "leads_finder": 110,
}
BASE = "https://api.apify.com/v2"


class ApifyManager:
    def __init__(self):
        self.headers = {"Authorization": f"Bearer {APIFY_API_TOKEN}"}

    async def get_input_schema(self, scraper: str) -> dict:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{BASE}/acts/{scraper}/input-schema", headers=self.headers, timeout=15)
            r.raise_for_status(); return r.json()

    async def run(self, scraper: str, params: Dict) -> dict:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{BASE}/acts/{scraper}/runs", headers=self.headers, json=params, timeout=30)
            r.raise_for_status(); d = r.json()["data"]
            return {"run_id": d["id"], "dataset_id": d["defaultDatasetId"]}

    async def status(self, run_id: str) -> dict:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{BASE}/actor-runs/{run_id}", headers=self.headers, timeout=15)
            r.raise_for_status(); d = r.json()["data"]
            return {"status": d["status"], "dataset_id": d["defaultDatasetId"]}

    async def result(self, dataset_id: str) -> List[Dict]:
        """MANDATORY — retrieves data + finalizes billing. NEVER skip."""
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{BASE}/datasets/{dataset_id}/items", headers=self.headers, timeout=60)
            r.raise_for_status(); return r.json()

    async def run_and_wait(self, scraper: str, params: Dict) -> List[Dict]:
        rd = await self.run(scraper, params)
        await asyncio.sleep(SCRAPER_CATALOG.get(scraper, 60))
        for _ in range(10):
            s = await self.status(rd["run_id"])
            if s["status"] == "SUCCEEDED": return await self.result(s["dataset_id"])
            if s["status"] in ("FAILED","ABORTED","TIMED-OUT"): raise RuntimeError(s["status"])
            await asyncio.sleep(10)
        raise TimeoutError(f"{scraper} timed out")
