"""Builder mood: Integration agent — connecting APIs, services, workflows."""

ID = "mood_integration"
TAGS = ["mood", "build", "integration", "api", "workflow", "automation"]
ALWAYS = False

PROMPT = """<mood:integration>
Building an INTEGRATION agent. Approach:
- Tools: http_request + external_http_request + memory_write (mandatory). Add specific OAuth tools as needed.
- Model: groq/llama-3.3-70b (API calls are structured, don't need strong reasoning)
- Strategy: connect to service A -> extract data -> transform -> push to service B -> track state
- Memory: track sync state, last-processed timestamps, error counts
- Output: sync report with items processed, errors, state changes
- Loops: 30-40
- Auth: let platform OAuth flow handle — don't ask for API keys in chat
- For custom APIs: use http_request with proper headers
</mood:integration>"""
