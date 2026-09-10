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
from personal_assistant import PersonalAssistantRequest, handoff_to_command_center
from write_approval import VerifiedGmailDraftRequest
from execution_adapter import ExecutionEngineAdapter


store = TaskStore(settings.db_path, settings.audit_log_path)
store.seed_defaults()
runtime = Runtime(store, settings)

execution_engine = ExecutionEngineAdapter(
    enabled=settings.execution_engine_enabled,
    authorized_roots=list(settings.execution_engine_workspace_roots),
    audit_log_path=settings.execution_engine_audit_log,
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    await runtime.start()
    yield
    await runtime.stop()


app = FastAPI(title="AI Agent Command Center", version="0.1.0", lifespan=lifespan)



class ExecutionRequest(BaseModel):
    capability: Literal[
        "list_directory",
        "read_text_file",
        "search_text",
        "git_status",
        "git_diff",
        "git_log",
        "run_command_profile",
    ]
    path: str | None = None
    query: str | None = None
    profile_id: str | None = None
    task_id: str | None = None
    max_results: int = Field(default=200, ge=1, le=1000)
    max_count: int = Field(default=20, ge=1, le=100)
class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10000)
    agent_name: str = "Orchestrator"
    priority: Literal["Critical", "High", "Medium", "Low"] = "Medium"
    side_effect_level: Literal["none", "external", "destructive"] = "none"
    requires_approval: bool = False


def classify_task_side_effect(
    title: str,
    description: str,
    explicit_level: str = "none",
) -> str:
    """Conservatively classify obvious task side effects before execution."""
    if explicit_level in {"external", "destructive"}:
        return explicit_level

    content = f"{title}\n{description}".lower()

    # Ignore explicitly negated mutation phrases so genuinely read-only
    # inspection requests are not incorrectly classified as side-effecting.
    actionable_content = content
    for phrase in (
        "do not modify",
        "do not edit",
        "do not write",
        "do not overwrite",
        "do not replace",
        "do not rename",
        "do not move",
        "do not delete",
        "do not remove",
        "do not erase",
        "without modifying",
        "without editing",
        "without changing",
        "no changes",
    ):
        actionable_content = actionable_content.replace(phrase, "")

    destructive_actions = (
        "delete ",
        "remove ",
        "erase ",
        "drop ",
        "destroy ",
    )

    external_actions = (
        "replace ",
        "modify ",
        "edit ",
        "write ",
        "overwrite ",
        "rename ",
        "move ",
        "create file",
        "save file",
        "send email",
        "send the email",
        "modify calendar",
        "create calendar",
        "delete calendar",
        "deploy ",
        "install ",
        "uninstall ",
        "execute command",
        "run command",
    )

    file_or_system_target = (
        "\\" in content
        or ":\\" in content
        or ".py" in content
        or ".js" in content
        or ".ts" in content
        or ".html" in content
        or ".css" in content
        or ".json" in content
        or ".sql" in content
        or ".yaml" in content
        or ".yml" in content
        or " file" in content
        or "repository" in content
        or "database" in content
    )

    if file_or_system_target and any(action in actionable_content for action in destructive_actions):
        return "destructive"

    if file_or_system_target and any(action in actionable_content for action in external_actions):
        return "external"

    account_side_effects = (
        "send email",
        "send the email",
        "create calendar",
        "modify calendar",
        "delete calendar",
        "deploy ",
    )

    if any(action in content for action in account_side_effects):
        return "external"

    return "none"


def should_defer_exact_approval(title: str, description: str) -> bool:
    """Return true when a task should wait for an exact verified approval."""
    content = f"{title}\n{description}".lower()
    verified_execution_markers = (
        "use verified replace text",
        "verified replace text",
        "verified_replace_text",
        "use verified write text file",
        "verified write text file",
        "verified_write_text_file",
    )
    return any(marker in content for marker in verified_execution_markers)


class GmailDraftApprovalRequest(BaseModel):
    to: list[str] = Field(min_length=1)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=50000)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "ai-agent-command-center",
        "database": "ok",
        "openai_key_configured": api_key_configured(),
        "agent_execution_enabled": settings.enable_agent_runs,
        "execution_engine_enabled": settings.execution_engine_enabled,
        "execution_engine_ready": execution_engine.ready,
        "authorized_workspace_count": len(settings.execution_engine_workspace_roots),
    }



@app.get("/api/execution/status")
def execution_status() -> dict:
    return {
        "enabled": settings.execution_engine_enabled,
        "ready": execution_engine.ready,
        "authorized_workspace_count": len(settings.execution_engine_workspace_roots),
    }

@app.get("/api/summary")
def summary() -> dict:
    return {
        **store.summary(),
        "agents": store.list_agents(),
        "tasks": store.list_task_visibility(25),
        "approvals": store.list_approvals(),
        "activity": store.list_activity(30),
        "execution_note": "Agent execution is opt-in via ENABLE_AGENT_RUNS=true; enabled connectors remain capability-scoped and approval-gated where required.",
    }


@app.post("/api/assistant/handoff", status_code=201)
def assistant_handoff(request: PersonalAssistantRequest) -> dict:
    inferred_level = classify_task_side_effect(
        request.title or "",
        request.request,
        request.side_effect_level,
    )

    safe_request = request.model_copy(
        update={
            "side_effect_level": inferred_level,
        }
    )

    result = handoff_to_command_center(store, safe_request)
    return result.model_dump()


@app.get("/api/tasks")
def tasks() -> list[dict]:
    return store.list_tasks()


@app.post("/api/tasks", status_code=201)
def create_task(request: TaskCreate) -> dict:
    payload = request.model_dump()

    inferred_level = classify_task_side_effect(
        request.title,
        request.description,
        request.side_effect_level,
    )

    payload["side_effect_level"] = inferred_level
    payload["requires_approval"] = bool(
        request.requires_approval or inferred_level != "none"
    )
    payload["defer_exact_approval"] = should_defer_exact_approval(
        request.title,
        request.description,
    )

    return store.create_task(**payload)


@app.post("/api/tasks/{task_id}/archive")
def archive_task(task_id: str) -> dict:
    try:
        archived = store.archive_task(task_id)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if archived is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    return archived



@app.post("/api/gmail/drafts/request", status_code=201)
def request_gmail_draft_approval(
    request: GmailDraftApprovalRequest,
) -> dict:
    to = tuple(
        address.strip()
        for address in request.to
        if address.strip()
    )
    cc = tuple(
        address.strip()
        for address in request.cc
        if address.strip()
    )
    bcc = tuple(
        address.strip()
        for address in request.bcc
        if address.strip()
    )
    subject = request.subject.strip()
    body = request.body.strip()

    if not to:
        raise HTTPException(
            status_code=400,
            detail="At least one recipient is required.",
        )

    if not subject:
        raise HTTPException(
            status_code=400,
            detail="subject is required.",
        )

    if not body:
        raise HTTPException(
            status_code=400,
            detail="body is required.",
        )

    task = store.create_task(
        title=f"Gmail draft: {subject[:160]}",
        description="Prepare approved Gmail draft.",
        agent_name="Email / Calendar",
        priority="Medium",
        side_effect_level="external",
        requires_approval=False,
        metadata={
            "workflow_type": "native_gmail_draft",
        },
        defer_exact_approval=True,
    )

    exact_request = VerifiedGmailDraftRequest(
        task_id=str(task["id"]),
        capability="gmail.draft.create",
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        body=body,
    )

    approval = store.create_exact_approval(
        exact_request,
        reason="Create this exact Gmail draft",
    )

    return {
        "task": task,
        "approval": approval,
        "draft": {
            "to": list(to),
            "cc": list(cc),
            "bcc": list(bcc),
            "subject": subject,
            "body": body,
        },
        "status": "awaiting_approval",
    }


@app.post("/api/approvals/{approval_id}/{decision}")
def decide_approval(approval_id: str, decision: Literal["approved", "rejected"]) -> dict:
    try:
        return store.decide_approval(approval_id, decision)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc



@app.post("/api/execution/request")
def execution_request(request: ExecutionRequest):
    if not execution_engine.ready:
        raise HTTPException(
            status_code=503,
            detail="Shared Local Execution Engine is disabled or not ready.",
        )

    try:
        if request.capability == "list_directory":
            if not request.path:
                raise ValueError("path is required.")
            return execution_engine.list_directory(
                request.path,
                task_id=request.task_id,
            )

        if request.capability == "read_text_file":
            if not request.path:
                raise ValueError("path is required.")
            return execution_engine.read_text_file(
                request.path,
                task_id=request.task_id,
            )

        if request.capability == "search_text":
            if not request.path or request.query is None:
                raise ValueError("path and query are required.")
            return execution_engine.search_text(
                request.path,
                request.query,
                task_id=request.task_id,
                max_results=request.max_results,
            )

        if request.capability == "git_status":
            if not request.path:
                raise ValueError("path is required.")
            return execution_engine.git_status(
                request.path,
                task_id=request.task_id,
            )

        if request.capability == "git_diff":
            if not request.path:
                raise ValueError("path is required.")
            return execution_engine.git_diff(
                request.path,
                task_id=request.task_id,
            )

        if request.capability == "git_log":
            if not request.path:
                raise ValueError("path is required.")
            return execution_engine.git_log(
                request.path,
                task_id=request.task_id,
                max_count=request.max_count,
            )

        if request.capability == "run_command_profile":
            if not request.path or not request.profile_id:
                raise ValueError("path and profile_id are required.")
            result = execution_engine.run_command_profile(
                request.profile_id,
                request.path,
                task_id=request.task_id,
            )
            return result.__dict__

        raise PermissionError("Capability denied.")

    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
@app.get("/api/activity")
def activity() -> list[dict]:
    return store.list_activity()


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=False)



