"""Builder mood: Scraper agent — web scraping, data extraction, structured output."""

ID = "mood_scraper"
TAGS = ["mood", "build", "scraping", "data"]
ALWAYS = False

PROMPT = """<mood:scraper>
Building a SCRAPER agent. Approach:
- Tools: web_search + scrape_page + fetch_url + memory_write (mandatory)
- Model: groq/llama-3.3-70b (scraping is more about tool use than reasoning)
- Strategy: identify target URLs -> scrape each -> extract structured data -> compile
- Memory: track scraped URLs to avoid re-scraping on next run
- Output: structured data (JSON/table format), with source URLs
- Loops: 40-50 (each page = 2-3 loops: navigate + scrape + parse)
- WARN about scope risk if target is broad (many pages/entities)
</mood:scraper>"""
