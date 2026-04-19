"""Builder mood: Code agent — development, analysis, CI/CD."""

ID = "mood_code"
TAGS = ["mood", "build", "code", "development", "github", "programming"]
ALWAYS = False

PROMPT = """<mood:code>
Building a CODE agent. Approach:
- Tools: execute_code + code_visualizer_scan + git_clone + git_push (mandatory)
- Model: anthropic/claude-3-5-sonnet (best for code tasks)
- Strategy: clone/access repo -> analyze -> make changes -> test -> push
- Temperature: 0.3-0.4 (code needs precision, not creativity)
- Output: code changes committed, test results, analysis reports
- Loops: 40-50 (complex code tasks need many iterations)
- For analysis-only: code_visualizer_scan gives AST/dependency graphs
</mood:code>"""
