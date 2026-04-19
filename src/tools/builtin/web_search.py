"""Web Search — Tavily API with key rotation, DuckDuckGo fallback"""
import os
import logging
from urllib.parse import quote_plus
import httpx

logger = logging.getLogger(__name__)


async def web_search(query: str, context: str = "") -> dict:
    """Search the web. Tries Tavily first (advanced search), falls back to DuckDuckGo."""
    if not query or not query.strip():
        return {"error": "Empty query"}

    # Try Tavily first (has API keys in production)
    tavily_raw = os.getenv("TAVILY_API_KEY", "")
    tavily_keys = [k.strip() for k in tavily_raw.split(",") if k.strip()]

    for key in tavily_keys:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post("https://api.tavily.com/search", json={
                    "api_key": key,
                    "query": query,
                    "max_results": 8,
                    "search_depth": "advanced",
                    "include_answer": True,
                    "include_raw_content": False,
                })
                if resp.status_code == 200:
                    data = resp.json()
                    results = []
                    for item in data.get("results", []):
                        results.append({
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "snippet": item.get("content", "")[:500],
                        })
                    out = {"query": query, "results": results, "count": len(results)}
                    if data.get("answer"):
                        out["answer"] = data["answer"]
                    return out
        except Exception as e:
            logger.warning(f"Tavily key failed: {e}")
            continue

    # Fallback: DuckDuckGo instant answer API
    try:
        url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_redirect=1&no_html=1"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "DevSwat-AgentArchitect/1.0",
                "Accept": "application/json",
            })
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for topic in data.get("RelatedTopics", []):
                    if isinstance(topic, dict) and topic.get("Text") and topic.get("FirstURL"):
                        results.append({"title": topic["Text"], "url": topic["FirstURL"]})
                return {
                    "query": query,
                    "heading": data.get("Heading"),
                    "abstract": data.get("Abstract"),
                    "results": results[:10],
                    "count": len(results[:10]),
                }
    except Exception as e:
        logger.error(f"DuckDuckGo fallback failed: {e}")

    return {"error": "All search providers failed", "query": query}
