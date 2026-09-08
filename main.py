from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent import api_key_configured
from config import settings
from runtime import Runtime
from store import TaskStore


store = TaskStore(settings.db_path, settings.audit_log_path)
store.seed_defaults()
runtime = Runtime(store, settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await runtime.start()
    yield
    await runtime.stop()


app = FastAPI(title="AI Agent Command Center", version="0.1.0", lifespan=lifespan)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10000)
    agent_name: str = "Orchestrator"
    priority: Literal["Critical", "High", "Medium", "Low"] = "Medium"
    side_effect_level: Literal["none", "external", "destructive"] = "none"
    requires_approval: bool = False


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "ai-agent-command-center",
        "database": "ok",
        "openai_key_configured": api_key_configured(),
        "agent_execution_enabled": settings.enable_agent_runs,
    }


@app.get("/api/summary")
def summary() -> dict:
    return {
        **store.summary(),
        "agents": store.list_agents(),
        "tasks": store.list_tasks(25),
        "approvals": store.list_approvals(),
        "activity": store.list_activity(30),
        "execution_note": "Agent execution is opt-in via ENABLE_AGENT_RUNS=true; external connectors are not enabled in Phase 1.",
    }


@app.get("/api/tasks")
def tasks() -> list[dict]:
    return store.list_tasks()


@app.post("/api/tasks", status_code=201)
def create_task(request: TaskCreate) -> dict:
    return store.create_task(**request.model_dump())


@app.post("/api/approvals/{approval_id}/{decision}")
def decide_approval(approval_id: str, decision: Literal["approved", "rejected"]) -> dict:
    try:
        return store.decide_approval(approval_id, decision)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/activity")
def activity() -> list[dict]:
    return store.list_activity()


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=False)
