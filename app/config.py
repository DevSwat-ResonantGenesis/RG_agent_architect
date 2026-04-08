"""
RG Agent Architect — Configuration

All service URLs, LLM keys, and orchestrator parameters.
Twin architecture: twin.md Sections 1-3.
"""
import os


class Settings:
    # ── Downstream Services (Docker network) ──
    AGENT_ENGINE_URL: str = os.getenv("AGENT_ENGINE_URL", "http://agent_engine_service:8000")
    MEMORY_SERVICE_URL: str = os.getenv("MEMORY_SERVICE_URL", "http://memory_service:8000")
    CHAT_SERVICE_URL: str = os.getenv("CHAT_SERVICE_URL", "http://chat_service:8000")

    # ── LLM API Keys ──
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_API_KEY_2: str = os.getenv("GROQ_API_KEY_2", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # ── Model Selection ──
    # Twin: Builder = high-reasoning (expensive), Runner = smaller (cheap)
    DEFAULT_PROVIDER: str = "groq"
    DEFAULT_MODEL: str = "llama-3.3-70b-versatile"
    FAST_MODEL: str = "llama-3.1-8b-instant"
    REASONING_MODEL: str = "gpt-4o"

    # ── Execution ──
    EXECUTION_TIMEOUT: float = float(os.getenv("EXECUTION_TIMEOUT", "180"))
    POLL_INTERVAL: float = 5.0
    POLL_MAX_ROUNDS: int = 40

    # ── Orchestrator ReAct Loop ──
    # Twin's orchestrator iterates: think → tool_call → observe → repeat
    ORCHESTRATOR_MAX_ITERATIONS: int = 20
    ORCHESTRATOR_MAX_TOKENS: int = 4096
    ORCHESTRATOR_HISTORY_DEPTH: int = 10
    ORCHESTRATOR_MSG_TRUNCATE: int = 2000

    # ── Task Profiles (twin-platform config) ──
    # Determines model, loops, temperature, budget per task complexity
    TASK_PROFILES: dict = {
        "simple":   {"max_loops": 20, "temperature": 0.4, "model": "llama-3.3-70b-versatile", "max_tokens": 30000, "max_credits": 50},
        "medium":   {"max_loops": 35, "temperature": 0.55, "model": "llama-3.3-70b-versatile", "max_tokens": 50000, "max_credits": 100},
        "complex":  {"max_loops": 45, "temperature": 0.65, "model": "gpt-4o", "max_tokens": 80000, "max_credits": 200},
        "creative": {"max_loops": 25, "temperature": 0.75, "model": "llama-3.3-70b-versatile", "max_tokens": 50000, "max_credits": 100},
    }

    # ── Billing Plans (twin-platform config) ──
    PLANS: dict = {
        "free":  {"price": 0,    "credits": 2200,   "email_limit": 50},
        "plus":  {"price": 20,   "credits": 2000,   "email_limit": 100},
        "pro":   {"price": 200,  "credits": 20000,  "email_limit": 1000},
        "max":   {"price": 1000, "credits": 100000, "email_limit": 5000},
    }

    def groq_keys(self) -> list[str]:
        """Return all valid Groq API keys (supports comma-separated)."""
        keys = []
        for raw in (self.GROQ_API_KEY, self.GROQ_API_KEY_2):
            for k in raw.split(","):
                k = k.strip()
                if k and k not in keys:
                    keys.append(k)
        return keys


settings = Settings()
