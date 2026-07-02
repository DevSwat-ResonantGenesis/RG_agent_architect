"""Twin Platform — Configuration Constants"""
import os

# ── Infrastructure URLs (full platform access) ──
AGENT_ENGINE_URL = os.getenv("AGENT_ENGINE_URL", "http://agent_engine_service:8000")
MEMORY_SERVICE_URL = os.getenv("MEMORY_SERVICE_URL", "http://memory_service:8000")
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth_service:8000")
BILLING_SERVICE_URL = os.getenv("BILLING_SERVICE_URL", "http://billing_service:8000")
BLOCKCHAIN_SERVICE_URL = os.getenv("BLOCKCHAIN_SERVICE_URL", "http://blockchain_service:8000")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification_service:8000")
CODE_EXECUTION_SERVICE_URL = os.getenv("CODE_EXECUTION_SERVICE_URL", "http://code_execution_service:8002")
STORAGE_SERVICE_URL = os.getenv("STORAGE_SERVICE_URL", "http://storage_service:8000")
WORKFLOW_SERVICE_URL = os.getenv("WORKFLOW_SERVICE_URL", "http://workflow_service:8000")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:8000")
SANDBOX_RUNNER_URL = os.getenv("SANDBOX_RUNNER_URL", "http://sandbox_runner_service:9001")
AST_ANALYSIS_URL = os.getenv("AST_ANALYSIS_SERVICE_URL", "http://rg_ast_analysis:8000")
ED_SERVICE_URL = os.getenv("ED_SERVICE_URL", "http://ed_service:8000")
LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://llm_service:8000")

# ── Orchestrator tuning ──
ORCHESTRATOR_MAX_ITERATIONS = 30
MAX_TOKENS = 16000
HISTORY_DEPTH = 10
POLL_MAX_ROUNDS = 40
POLL_INTERVAL = 5
TIMEOUT = 180
BUILDER_MAX_LOOPS = 30

TASK_PROFILES = {
    "simple":   {"max_loops": 20, "temperature": 0.4, "model": "groq/llama-3.3-70b-versatile", "max_tokens": 60000, "max_credits": 50},
    "medium":   {"max_loops": 35, "temperature": 0.55, "model": "groq/llama-3.3-70b-versatile", "max_tokens": 100000, "max_credits": 100},
    "complex":  {"max_loops": 45, "temperature": 0.65, "model": "openai/gpt-4o", "max_tokens": 128000, "max_credits": 200},
    "creative": {"max_loops": 25, "temperature": 0.75, "model": "groq/llama-3.3-70b-versatile", "max_tokens": 100000, "max_credits": 100},
}

PLANS = {
    "free":  {"price": 0,    "credits": 2200,   "email_limit": 50},
    "plus":  {"price": 20,   "credits": 2000,   "email_limit": 100},
    "pro":   {"price": 200,  "credits": 20000,  "email_limit": 1000},
    "max":   {"price": 1000, "credits": 100000, "email_limit": 5000},
}

# ── API Keys ──
# LLM keys are NOT needed here — all LLM calls go through the unified
# LLM service which manages its own keys, BYOK, billing, and fallback.
# Only keep keys for services the architect calls directly.
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "")
MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "")

# ── Local file storage (fallback) ──
DATA_DIR = os.getenv("DATA_DIR", "data")
FILES_DIR = os.path.join(DATA_DIR, "files")
