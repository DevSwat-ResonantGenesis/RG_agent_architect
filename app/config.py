"""
RG Agent Architect — Configuration
"""
import os


class Settings:
    # Downstream services (Docker network names)
    AGENT_ENGINE_URL: str = os.getenv("AGENT_ENGINE_URL", "http://agent_engine_service:8000")
    MEMORY_SERVICE_URL: str = os.getenv("MEMORY_SERVICE_URL", "http://memory_service:8000")
    CHAT_SERVICE_URL: str = os.getenv("CHAT_SERVICE_URL", "http://chat_service:8000")

    # LLM API keys
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_API_KEY_2: str = os.getenv("GROQ_API_KEY_2", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # Defaults
    DEFAULT_PROVIDER: str = "groq"
    DEFAULT_MODEL: str = "llama-3.3-70b-versatile"
    FAST_MODEL: str = "llama-3.1-8b-instant"
    REASONING_MODEL: str = "gpt-4o"

    # Execution
    EXECUTION_TIMEOUT: float = float(os.getenv("EXECUTION_TIMEOUT", "180"))
    POLL_INTERVAL: float = 5.0
    POLL_MAX_ROUNDS: int = 40  # 5s * 40 = 200s = 3.3 min polling window

    # Orchestrator ReAct loop
    ORCHESTRATOR_MAX_ITERATIONS: int = 20  # was 10 — need more for complex flows
    ORCHESTRATOR_MAX_TOKENS: int = 4096  # was 2000 — LLM needs room to think
    ORCHESTRATOR_HISTORY_DEPTH: int = 10  # was 6 — keep more conversation context
    ORCHESTRATOR_MSG_TRUNCATE: int = 2000  # was 1000 — preserve message detail

    def groq_keys(self) -> list[str]:
        keys = []
        for raw in (self.GROQ_API_KEY, self.GROQ_API_KEY_2):
            for k in raw.split(","):
                k = k.strip()
                if k and k not in keys:
                    keys.append(k)
        return keys


settings = Settings()
