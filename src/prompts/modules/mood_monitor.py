"""Builder mood: Monitor agent — watch for changes, alert on triggers."""

ID = "mood_monitor"
TAGS = ["mood", "build", "monitoring", "alerts"]
ALWAYS = False

PROMPT = """<mood:monitor>
Building a MONITOR agent. Approach:
- Tools: web_search + fetch_url + scrape_page + memory_write + send_email (mandatory)
- Model: groq/llama-3.3-70b (monitoring is repetitive, doesn't need strong reasoning)
- Strategy: check source -> compare to last known state (memory_read) -> detect changes -> alert if changed -> update state (memory_write)
- Memory: CRITICAL — memory_write stores last-seen state, memory_read compares. Without it, every run reports everything as "new."
- Output: change report with what changed, when, and significance
- Loops: 20-30 (focused on specific sources)
- ALWAYS suggest set_trigger after build — monitoring needs a schedule
</mood:monitor>"""
