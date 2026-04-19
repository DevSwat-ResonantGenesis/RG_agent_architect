"""Builder mood: Content agent — writing, social media, newsletters."""

ID = "mood_content"
TAGS = ["mood", "build", "content", "writing", "social", "newsletter"]
ALWAYS = False

PROMPT = """<mood:content>
Building a CONTENT agent. Approach:
- Tools: web_search + fetch_url + generate_image + send_email (mandatory). Add memory_write for editorial calendar.
- Model: openai/gpt-4o (creative writing needs strong model) or groq/llama-3.3-70b for simpler content
- Strategy: research topic -> gather source material -> write content -> generate visuals if needed -> publish/email
- Temperature: 0.7-0.8 (creative output needs variety)
- Memory: track published content to avoid repetition
- Output: formatted content pieces ready to publish
- Loops: 30 (research + write + revise)
</mood:content>"""
