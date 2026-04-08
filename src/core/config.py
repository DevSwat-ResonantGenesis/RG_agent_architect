"""Twin Platform — Configuration Constants"""
import os

# ── Infrastructure URLs ──
DATABASE_URL = os.getenv("ARCHITECT_DATABASE_URL", os.getenv("DATABASE_URL", ""))
LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://llm_service:8000")
MEMORY_SERVICE_URL = os.getenv("MEMORY_SERVICE_URL", "http://memory_service:8000")

# ── Orchestrator tuning ──
ORCHESTRATOR_MAX_ITERATIONS = 20
MAX_TOKENS = 4096
HISTORY_DEPTH = 10
POLL_MAX_ROUNDS = 40
POLL_INTERVAL = 5
TIMEOUT = 180
BUILDER_MAX_LOOPS = 30

TASK_PROFILES = {
    "simple":   {"max_loops": 20, "temperature": 0.4, "model": "groq/llama-3.3-70b-versatile", "max_tokens": 30000, "max_credits": 50},
    "medium":   {"max_loops": 35, "temperature": 0.55, "model": "groq/llama-3.3-70b-versatile", "max_tokens": 50000, "max_credits": 100},
    "complex":  {"max_loops": 45, "temperature": 0.65, "model": "openai/gpt-4o", "max_tokens": 80000, "max_credits": 200},
    "creative": {"max_loops": 25, "temperature": 0.75, "model": "groq/llama-3.3-70b-versatile", "max_tokens": 50000, "max_credits": 100},
}

PLANS = {
    "free":  {"price": 0,    "credits": 2200,   "email_limit": 50},
    "plus":  {"price": 20,   "credits": 2000,   "email_limit": 100},
    "pro":   {"price": 200,  "credits": 20000,  "email_limit": 1000},
    "max":   {"price": 1000, "credits": 100000, "email_limit": 5000},
}

# ── API Keys (from .env.production) ──
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_KEY_2 = os.getenv("GROQ_API_KEY_2", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "")
MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "")

# ── Local file storage (fallback) ──
DATA_DIR = os.getenv("DATA_DIR", "data")
FILES_DIR = os.path.join(DATA_DIR, "files")
