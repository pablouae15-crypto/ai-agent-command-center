# AI Agent Command Center

This is a Windows-friendly local AI Agent Command Center with an orchestrator, routed specialist agents, persistent SQLite state, controlled local execution, approval workflows, connector access, JSONL audit logs, and a local web dashboard.

## Safety defaults

- Agent execution is controlled by `ENABLE_AGENT_RUNS`. The current local configuration has it enabled; change this setting deliberately because model-backed runs may consume API credits.
- Tasks marked `external` or `destructive` automatically require human approval.
- Email / Calendar and Research / News are available through controlled, capability-scoped connectors. HR & Compliance and Job Tracker are active specialists. External or destructive actions still require approval.
- `.env` is ignored by Git. Keep the API key in `.env`; never commit it.

## Run locally on Windows

```powershell
cd "D:\AI-Agent-Command-Center"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python main.py
```

Open [http://127.0.0.1:8421](http://127.0.0.1:8421). Readiness is available at [http://127.0.0.1:8421/health](http://127.0.0.1:8421/health).

Agent execution is controlled by `ENABLE_AGENT_RUNS` in `.env`. The current local configuration has agent execution enabled. The service uses `OPENAI_MODEL` and the locally stored `OPENAI_API_KEY` for model-backed runs. Local execution is separately controlled by `EXECUTION_ENGINE_ENABLED` and authorized workspace roots.

## Tests

Run the full regression suite:

```powershell
Set-Location "D:\AI-Agent-Command-Center"
& ".\.venv\Scripts\python.exe" -m pytest -q
```

Current verified baseline: `204 passed`.

The suite covers API behavior, approvals, structured task outcomes, specialist routing, controlled execution, connector behavior, dashboard behavior, and regression protection.

## Windows autostart

For a local-process fallback, register the included Scheduled Task at logon:

```powershell
cd "D:\AI-Agent-Command-Center"
powershell -ExecutionPolicy Bypass -File scripts\register-startup-task.ps1
```
