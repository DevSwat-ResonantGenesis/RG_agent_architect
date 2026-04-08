"""Scrape Page — Firecrawl (summary → markdown, actions, CSS selectors)"""
import httpx
from typing import Dict, List, Optional
from src.core.config import FIRECRAWL_API_KEY

async def scrape_page(url: str, format: str = "markdown", wait_for: int = 0,
                      actions: Optional[List[Dict]] = None, include_tags: Optional[List[str]] = None,
                      exclude_tags: Optional[List[str]] = None, timeout: int = 30000, mobile: bool = False) -> dict:
    payload = {"url": url, "formats": [format], "waitFor": wait_for, "timeout": timeout, "mobile": mobile}
    if actions: payload["actions"] = actions
    if include_tags: payload["includeTags"] = include_tags
    if exclude_tags: payload["excludeTags"] = exclude_tags
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}"}, json=payload, timeout=timeout/1000+10)
        resp.raise_for_status()
        return resp.json()
