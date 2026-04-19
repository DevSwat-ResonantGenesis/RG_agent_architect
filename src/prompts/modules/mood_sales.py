"""Builder mood: Sales agent — lead gen, outreach, CRM automation."""

ID = "mood_sales"
TAGS = ["mood", "build", "sales", "leads", "outreach", "crm"]
ALWAYS = False

PROMPT = """<mood:sales>
Building a SALES agent. Approach:
- Tools: web_search + fetch_url + scrape_platforms + send_email + memory_write (mandatory)
- Model: openai/gpt-4o (personalized outreach needs strong reasoning)
- Strategy: find leads (search/scrape) -> enrich (fetch company info) -> draft personalized message -> send -> track in memory
- Memory: track contacted leads, response status, conversation stage
- Output: outreach emails sent + lead tracker update
- Loops: 40-50 (each lead = 3-4 loops: find + enrich + draft + send)
- WARN: scope risk if "all companies in X" — suggest sample first
- Auth: if CRM integration needed, let build flow handle OAuth
</mood:sales>"""
