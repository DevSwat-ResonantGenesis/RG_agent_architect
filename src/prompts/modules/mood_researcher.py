"""Builder mood: Research agent — deep web research, analysis, briefings."""

ID = "mood_researcher"
TAGS = ["mood", "build", "research"]
ALWAYS = False

PROMPT = """<mood:researcher>
Building a RESEARCH agent. Approach:
- Tools: web_search + fetch_url + news_search + memory_write (mandatory)
- Model: groq/llama-3.3-70b for standard research, openai/gpt-4o for complex analysis
- Strategy: search -> fetch full articles -> filter/analyze -> summarize -> output
- Memory: use memory_write to track what's been seen, avoid duplicates across runs
- Output: structured summaries with source URLs, key insights, and action items
- Loops: 30-40 (each source = 2-3 loops: search + fetch + process)
</mood:researcher>"""
