"""Scrape Page — Direct HTTP fetch with HTML text extraction"""
import re
import logging
import httpx
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _html_to_text(html: str, max_chars: int = 12000) -> str:
    """Basic HTML to text extraction — strips tags, scripts, styles."""
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars]


async def scrape_page(url: str, format: str = "markdown", wait_for: int = 0,
                      actions: Optional[List[Dict]] = None, include_tags: Optional[List[str]] = None,
                      exclude_tags: Optional[List[str]] = None, timeout: int = 30000, mobile: bool = False) -> dict:
    """Fetch a URL and extract its text content."""
    if not url or not url.strip():
        return {"error": "Empty URL"}

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=_HEADERS) as client:
            resp = await client.get(url)
            content_type = (resp.headers.get("content-type") or "").lower()

            if resp.status_code != 200:
                return {"url": url, "error": f"HTTP {resp.status_code}", "status": resp.status_code}

            if "json" in content_type:
                try:
                    return {"url": url, "status": 200, "content_type": "json", "data": resp.json()}
                except Exception:
                    pass

            text = _html_to_text(resp.text)
            title_match = re.search(r'<title[^>]*>(.*?)</title>', resp.text, re.IGNORECASE | re.DOTALL)
            title = title_match.group(1).strip() if title_match else ""

            return {
                "url": url,
                "status": 200,
                "title": title,
                "content_type": content_type.split(";")[0].strip(),
                "text": text,
                "length": len(text),
            }
    except Exception as e:
        logger.error(f"scrape_page failed for {url}: {e}")
        return {"url": url, "error": f"Fetch failed: {str(e)[:200]}"}
