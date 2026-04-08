"""Web Search — Perplexity AI"""
import httpx
from src.core.config import PERPLEXITY_API_KEY

async def web_search(query: str, context: str = "") -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}"},
            json={"model": "llama-3.1-sonar-large-128k-online",
                  "messages": [{"role": "system", "content": context or "Be precise."},
                               {"role": "user", "content": query}]}, timeout=30.0)
        resp.raise_for_status()
        d = resp.json()
        return {"answer": d["choices"][0]["message"]["content"], "citations": d.get("citations",[])}
