"""Model selection and execution parameters."""

ID = "models_config"
TAGS = ["build", "control", "config"]
ALWAYS = False

PROMPT = """<models>
Available models (pick based on task complexity):
- groq/llama-3.3-70b-versatile: Fast, cost-effective. DEFAULT for 90% of tasks.
- groq/llama-3.1-8b-instant: Ultra-fast for simple classification or routing.
- openai/gpt-4o: Strongest reasoning. Complex multi-step logic.
- anthropic/claude-3-5-sonnet-20241022: Excellent coding and structured analysis.

Execution parameters:
Simple tasks: max_loops=20, temp=0.3-0.5
Medium: max_loops=40, temp=0.5-0.6
Complex: max_loops=50, temp=0.6-0.7
Creative: max_loops=30, temp=0.7-0.8
</models>"""
