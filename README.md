# TBX AI Assistant Starter

Problem-statement-neutral boilerplate for an AI-focused financial hackathon project.

## Included

- React + TypeScript + Vite chat UI
- FastAPI backend with clean API/service/provider/tool boundaries
- Sarvam AI provider isolated behind an `LLMProvider` protocol
- Mock provider, so the complete flow works without an API key
- Generic tool registry with an example deterministic calculation
- PostgreSQL container ready for problem-specific persistence
- Health check, CORS configuration, tests and Docker Compose

## Start locally

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:5173. API documentation is at http://localhost:8000/docs.

The default `LLM_PROVIDER=mock` requires no external API. To use Sarvam, set
`LLM_PROVIDER=sarvam` and `SARVAM_API_KEY` in `.env`.

## Adapt on hack day

1. Add deterministic business functions in `backend/app/tools/`.
2. Register them in `ToolRegistry`.
3. Replace the neutral system prompt in `assistant/service.py`.
4. Add problem-specific Pydantic models and persistence.
5. Add corresponding React views without changing the provider layer.

The starter intentionally has no assumptions about budgeting, investment,
lending, personalization or the final TBX problem statement.

## Production hardening checklist

Before a real deployment, add authentication, migrations, persistent conversation
storage, secret management, request limits, telemetry and a user-confirmation
boundary for consequential actions. Keep calculations deterministic and use the
LLM only for interpretation, tool selection and explanation.

