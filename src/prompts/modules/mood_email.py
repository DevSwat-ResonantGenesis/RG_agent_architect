"""Builder mood: Email agent — sending, reading, automating email workflows."""

ID = "mood_email"
TAGS = ["mood", "build", "email", "communication"]
ALWAYS = False

PROMPT = """<mood:email>
Building an EMAIL agent. Approach:
- Tools: send_email + web_search + fetch_url + memory_write (mandatory)
- Model: groq/llama-3.3-70b (email drafting is straightforward)
- Strategy: gather data -> draft email -> personalize -> send -> track
- Memory: track sent emails, avoid duplicate sends
- Output: emails sent with delivery confirmation
- Loops: 20-30
- Auth: if SMTP needed, collect via present_options with Secret type for password
- NEVER include SMTP credentials in goal text
</mood:email>"""
