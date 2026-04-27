"""Tool synergies — recommended tool combinations per use case."""

ID = "tool_synergies"
TAGS = ["build", "control", "tools"]
ALWAYS = False

PROMPT = """<tool_synergies>
Research: web_search + fetch_url + news_search + memory_write — "fetch_url reads full articles, not just snippets"
Content: web_search + fetch_url + generate_image + send_email — "generate_image creates visuals alongside text"
Monitoring: web_search + fetch_url + scrape_page + memory_write + send_email — "memory_write tracks changes between runs"
Code: execute_code + git_clone + git_push — "full dev pipeline"
Sales: web_search + fetch_url + scrape_platforms + send_email + memory_write — "scrape_platforms finds leads, memory tracks outreach"
Data: web_search + scrape_page + execute_code + memory_write + google_sheets — "scrape + code for data processing, sheets for output"
Spreadsheets: google_sheets + web_search + memory_write — "read/write/create spreadsheets, track data over time"
Documents: google_docs + web_search + fetch_url — "create/read/append docs from web research"
Email: gmail_send + web_search + memory_write — "send emails with researched content, track what was sent"
</tool_synergies>"""
