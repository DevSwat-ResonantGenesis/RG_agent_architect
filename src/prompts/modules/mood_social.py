"""Builder mood: Social media agent — posting, monitoring, engagement."""

ID = "mood_social"
TAGS = ["mood", "build", "social", "twitter", "reddit", "linkedin", "community"]
ALWAYS = False

PROMPT = """<mood:social>
Building a SOCIAL MEDIA agent. Approach:
- Tools: web_search + scrape_page + create_rabbit_post + memory_write (mandatory). Add generate_image for visual posts.
- Model: groq/llama-3.3-70b for monitoring, openai/gpt-4o for content creation
- Strategy: monitor sources -> identify trending topics -> create/curate posts -> publish -> track engagement
- Memory: track posted content, trending topics, engagement metrics
- Output: posts published with links and engagement tracking
- Loops: 30-40
- For Reddit/Twitter monitoring: web_search + scrape_page
</mood:social>"""
