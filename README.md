# RG Agent Architect

Standalone orchestrator service for building and running autonomous agents on the Resonant Genesis platform.

## Architecture

```
app/
├── main.py              # FastAPI app
├── config.py            # Environment config
├── routers.py           # REST endpoints
└── services/
    ├── orchestrator.py  # Main orchestration logic (entry point)
    ├── prompts.py       # All LLM prompts (identity, modes, planning)
    ├── llm_client.py    # Groq/OpenAI with fallback
    ├── context.py       # Workspace/tools/memory fetching
    ├── builder.py       # Blueprint generation, agent creation
    └── runner.py        # Execution, polling, scheduling
```

## Endpoints

- `POST /architect/orchestrate` — Main entry point (intent classification → routing → response)
- `POST /architect/classify-intent` — Standalone intent classification
- `GET /architect/health` — Health check
- `GET /health` — Root health check

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_ENGINE_URL` | `http://agent_engine_service:8000` | Agent Engine service |
| `MEMORY_SERVICE_URL` | `http://memory_service:8000` | Memory service |
| `GROQ_API_KEY` | — | Groq API key(s), comma-separated |
| `GROQ_API_KEY_2` | — | Additional Groq key(s) |
| `OPENAI_API_KEY` | — | OpenAI fallback key |

## Docker

```bash
docker build -t rg_agent_architect .
docker run -p 8000:8000 rg_agent_architect
```
