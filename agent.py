from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agents import Agent, Runner, function_tool

from config import settings
from execution_adapter import ExecutionEngineAdapter
from store import TaskStore
from write_approval import VerifiedEditRequest, validate_stored_approval


def api_key_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


execution_engine = ExecutionEngineAdapter(
    enabled=settings.execution_engine_enabled,
    authorized_roots=list(settings.execution_engine_workspace_roots),
    audit_log_path=settings.execution_engine_audit_log,
)


@function_tool
def list_directory(path: str, task_id: str | None = None) -> str:
    """List safe files and directories inside an authorized workspace."""
    result = execution_engine.list_directory(path, task_id=task_id)
    return str(result)


@function_tool
def read_text_file(path: str, task_id: str | None = None) -> str:
    """Read a permitted text file inside an authorized workspace."""
    result = execution_engine.read_text_file(path, task_id=task_id)
    return str(result)


@function_tool
def search_text(
    path: str,
    query: str,
    task_id: str | None = None,
) -> str:
    """Search permitted text files inside an authorized workspace."""
    result = execution_engine.search_text(
        path,
        query,
        task_id=task_id,
        max_results=100,
    )
    return str(result)


@function_tool
def git_status(path: str, task_id: str | None = None) -> str:
    """Read Git working-tree status for an authorized repository."""
    result = execution_engine.git_status(path, task_id=task_id)
    return str(result)


@function_tool
def git_diff(path: str, task_id: str | None = None) -> str:
    """Read the current Git diff for an authorized repository."""
    result = execution_engine.git_diff(path, task_id=task_id)
    return str(result)


@function_tool
def git_log(
    path: str,
    max_count: int = 10,
    task_id: str | None = None,
) -> str:
    """Read recent Git history for an authorized repository."""
    result = execution_engine.git_log(
        path,
        task_id=task_id,
        max_count=max_count,
    )
    return str(result)


@function_tool
def run_command_profile(
    path: str,
    profile_id: str,
    task_id: str | None = None,
) -> str:
    """Run one named allowlisted command profile in an authorized workspace."""
    result = execution_engine.run_command_profile(
        profile_id,
        path,
        task_id=task_id,
    )

    return str(
        {
            "execution_id": result.execution_id,
            "status": result.status.value,
            "profile_id": result.profile_id,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timeout": result.timeout,
            "duration_ms": result.duration_ms,
            "failure_reason": result.failure_reason,
        }
    )



SANDBOX_ROOT = Path(r"D:\Shared-Local-Execution-Engine-Sandbox")


def _require_sandbox_path(path: str, *, repository: bool = False) -> None:
    sandbox = SANDBOX_ROOT.resolve()
    candidate = Path(path).resolve()

    if repository:
        if candidate != sandbox:
            raise PermissionError(
                "Verified edits require the repository path to be exactly "
                r"D:\Shared-Local-Execution-Engine-Sandbox."
            )
        return

    try:
        candidate.relative_to(sandbox)
    except ValueError as exc:
        raise PermissionError(
            "Verified edits are restricted to "
            r"D:\Shared-Local-Execution-Engine-Sandbox."
        ) from exc


def build_verified_replace_text_tool(
    store: TaskStore,
    task_id: str,
):
    @function_tool
    def verified_replace_text(
        approval_id: str,
        path: str,
        repository_path: str,
        old_text: str,
        new_text: str,
        expected_replacements: int = 1,
    ) -> str:
        """Perform one exact, human-approved text replacement in the disposable sandbox."""
        if not approval_id.strip():
            raise PermissionError("approval_id is required.")

        if expected_replacements < 1:
            raise ValueError("expected_replacements must be at least 1.")

        _require_sandbox_path(repository_path, repository=True)
        _require_sandbox_path(path)

        request = VerifiedEditRequest(
            task_id=task_id,
            capability="replace_text",
            path=path,
            repository_path=repository_path,
            verification_profile="sandbox_pytest",
            old_text=old_text,
            new_text=new_text,
            expected_replacements=expected_replacements,
        )

        approval_row = store.get_approval(approval_id)
        approval = validate_stored_approval(approval_row, request)

        result = execution_engine.verified_replace_text(
            path,
            old_text,
            new_text,
            repository_path=repository_path,
            verification_profile="sandbox_pytest",
            task_id=task_id,
            approval=approval,
            expected_replacements=expected_replacements,
        )
        return str(result)

    return verified_replace_text


def build_orchestrator(model: str, store: TaskStore, task_id: str) -> Agent:
    return Agent(
        name="Command Center Orchestrator",
        model=model,
        instructions=(
            "You are the local AI Command Center orchestrator. "
            "Use only the provided typed local tools when inspection or verification is needed. "
            "Never request or invent arbitrary shell, PowerShell, subprocess, deletion, move, rename, "
            "cleanup, Git push, force-push, reset, clean, rebase, deployment, production database, "
            "credential, secret, or .env access. "
            "Work only inside explicitly authorized workspaces. "
            "For the current integration phase, use the disposable sandbox only. "
            "Follow a controlled loop: inspect, reason, use the next necessary safe tool, examine the "
            "result, and continue only when justified. "
            "Do not repeatedly rerun the same verification without a reason. "
            "Stop immediately if a tool returns a security denial or approval requirement. "
            "The only permitted write operation is verified_replace_text, and it may be used only "
            "with a real stored approval_id matching the exact edit request. "
            "Never fabricate, construct, infer, or substitute an approval record or approval_id. "
            "Verified edits are restricted to D:\\Shared-Local-Execution-Engine-Sandbox, must use "
            "sandbox_pytest verification, and must rely on the execution engine rollback behavior "
            "if verification fails. "
            "When finished, summarize what you inspected, what verification ran, the result, and any "
            "remaining issue. Keep the final answer concise and evidence-based."
        ),
        tools=[
            list_directory,
            read_text_file,
            search_text,
            git_status,
            git_diff,
            git_log,
            run_command_profile,
            build_verified_replace_text_tool(store, task_id),
        ],
    )


async def run_orchestrator(
    task: dict[str, Any],
    model: str,
    store: TaskStore,
) -> str:
    if not api_key_configured():
        raise RuntimeError("OPENAI_API_KEY is not configured")

    if not execution_engine.ready:
        raise RuntimeError(
            "Shared Local Execution Engine is disabled or not ready."
        )

    result = await Runner.run(
        build_orchestrator(model, store, str(task["id"])),
        task["description"],
        max_turns=10,
    )

    output = getattr(result, "final_output", None)
    return str(output if output is not None else result)
