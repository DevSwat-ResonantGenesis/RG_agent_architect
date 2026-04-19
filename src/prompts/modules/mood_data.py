"""Builder mood: Data agent — collection, processing, analysis, spreadsheets."""

ID = "mood_data"
TAGS = ["mood", "build", "data", "analysis", "spreadsheet", "excel", "csv"]
ALWAYS = False

PROMPT = """<mood:data>
Building a DATA agent. Approach:
- Tools: web_search + scrape_page + execute_code + memory_write + google_sheets (mandatory)
- Model: openai/gpt-4o (data analysis benefits from strong reasoning)
- Strategy: collect data (search/scrape) -> process/clean (execute_code) -> analyze -> output structured format
- Temperature: 0.3-0.4 (data analysis needs precision)
- Memory: store intermediate results, track data sources
- Output: structured data in spreadsheet/JSON/CSV format
- Loops: 40-50 (collection + processing + analysis)
- For spreadsheet output: google_sheets or execute_code with pandas
</mood:data>"""
