# AI Agent Command Center — Phase 1 MVP

This is a small Windows-friendly local service for a 24/7 AI agent command center. It uses one OpenAI Agents SDK orchestrator, persistent SQLite state, a simple recurring-job scheduler, an approval queue, JSONL audit logs, and a local web dashboard. The Agents SDK uses the Responses API path for the orchestrator run.

## Safety defaults

- `ENABLE_AGENT_RUNS=false` by default, so startup and smoke tests do not spend API credits.
- Tasks marked `external` or `destructive` automatically require human approval.
- No email, calendar, HR, job-board, research, or file-writing connectors are enabled in Phase 1.
- `.env` is ignored by Git. Keep the API key in `.env`; never commit it.

## Run locally on Windows

```powershell
cd "C:\Users\pablo\OneDrive\Desktop\Paolo\AI Agent Command Center"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python main.py
```

Open [http://127.0.0.1:8421](http://127.0.0.1:8421). Readiness is available at [http://127.0.0.1:8421/health](http://127.0.0.1:8421/health).

Agent execution is intentionally off until you explicitly set `ENABLE_AGENT_RUNS=true` in `.env` and restart the service. The service will then use `OPENAI_MODEL` and the locally stored `OPENAI_API_KEY` for orchestrator runs. API usage is billed separately from ChatGPT Plus.

## Docker

```powershell
cd "C:\Users\pablo\OneDrive\Desktop\Paolo\AI Agent Command Center"
docker compose up --build -d
```

The compose file keeps execution disabled by default and persists `data` and `logs` on the host.

## Smoke test

After installing dependencies:

```powershell
python tests\smoke_test.py
```

It verifies `/health`, SQLite persistence, the task API, and the approval gate without using the OpenAI API.

## Windows autostart

For a local-process fallback, register the included Scheduled Task at logon:

```powershell
cd "C:\Users\pablo\OneDrive\Desktop\Paolo\AI Agent Command Center"
powershell -ExecutionPolicy Bypass -File scripts\register-startup-task.ps1
```

For a machine-wide service, use Docker Desktop with `restart: unless-stopped` or later wrap the process with a Windows service manager after Phase 1 has been exercised.

## Phase 2 candidates

Add one connector at a time (for example, read-only calendar or email first), persist connector credentials outside source control, add per-connector scopes, approval expiry, retries/backoff, metrics, backups, and a real multi-agent handoff only when the single orchestrator contract is proven.
