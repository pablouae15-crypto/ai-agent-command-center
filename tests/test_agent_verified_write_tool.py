from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from agents.tool_context import ToolContext

import agent
from agent import build_verified_write_text_file_tool
from engine.approvals import ApprovalRecord
from store import TaskStore
from write_approval import VerifiedFileWriteRequest


SANDBOX = r"D:\Shared-Local-Execution-Engine-Sandbox"
APP_PATH = rf"{SANDBOX}\app.py"


def make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(
        db_path=tmp_path / "command-center.db",
        audit_log_path=tmp_path / "audit.jsonl",
    )


def make_task(store: TaskStore) -> dict[str, object]:
    return store.create_task(
        title="Verified full-file write",
        description="Test approval-gated existing-file full write.",
        agent_name="Orchestrator",
        requires_approval=False,
    )


def current_app_text() -> str:
    return Path(APP_PATH).read_text(encoding="utf-8")


def current_app_sha256() -> str:
    return hashlib.sha256(
        Path(APP_PATH).read_bytes()
    ).hexdigest()


def make_request(
    task_id: str,
    *,
    content: str | None = None,
    expected_sha256: str | None = None,
    path: str = APP_PATH,
) -> VerifiedFileWriteRequest:
    return VerifiedFileWriteRequest(
        task_id=task_id,
        capability="write_text_file",
        path=path,
        repository_path=SANDBOX,
        verification_profile="sandbox_pytest",
        content=content if content is not None else current_app_text(),
        expected_sha256=(
            expected_sha256
            if expected_sha256 is not None
            else current_app_sha256()
        ),
    )


def approve(
    store: TaskStore,
    request: VerifiedFileWriteRequest,
) -> dict[str, object]:
    pending = store.create_exact_approval(request)
    return store.decide_approval(
        str(pending["id"]),
        "approved",
        decided_by="test-user",
    )


def invoke_tool(tool, payload: dict[str, object]) -> str:
    serialized = json.dumps(payload)

    context = ToolContext(
        context=None,
        tool_name="verified_write_text_file",
        tool_call_id="test-full-write",
        tool_arguments=serialized,
    )

    async def run() -> str:
        return await tool.on_invoke_tool(context, serialized)

    return asyncio.run(run())


class FakeExecutionEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def verified_write_text_file(
        self,
        path,
        content,
        *,
        repository_path,
        verification_profile,
        task_id,
        approval,
        expected_sha256=None,
        **kwargs,
    ):
        self.calls.append(
            {
                "path": path,
                "content": content,
                "repository_path": repository_path,
                "verification_profile": verification_profile,
                "task_id": task_id,
                "approval": approval,
                "expected_sha256": expected_sha256,
            }
        )

        return {
            "status": "verified",
            "verified": True,
        }


def valid_payload(
    approval_id: str,
    request: VerifiedFileWriteRequest,
) -> dict[str, object]:
    return {
        "approval_id": approval_id,
        "path": request.path,
        "repository_path": request.repository_path,
        "content": request.content,
        "expected_sha256": request.expected_sha256,
    }


def test_exact_approved_full_write_reaches_execution_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    approval_row = approve(store, request)

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_write_text_file_tool(store, str(task["id"]))
    result = invoke_tool(
        tool,
        valid_payload(str(approval_row["id"]), request),
    )

    assert "verified" in result
    assert len(fake_engine.calls) == 1

    call = fake_engine.calls[0]
    assert call["task_id"] == task["id"]
    assert call["path"] == APP_PATH
    assert call["repository_path"] == SANDBOX
    assert call["verification_profile"] == "sandbox_pytest"
    assert call["expected_sha256"] == request.expected_sha256
    assert isinstance(call["approval"], ApprovalRecord)


def test_pending_full_write_approval_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    pending = store.create_exact_approval(request)

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_write_text_file_tool(store, str(task["id"]))
    result = invoke_tool(
        tool,
        valid_payload(str(pending["id"]), request),
    )

    assert "Approval is not approved" in result
    assert fake_engine.calls == []


def test_modified_content_invalidates_full_write_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    approval_row = approve(store, request)

    payload = valid_payload(str(approval_row["id"]), request)
    payload["content"] = request.content + "\n# unauthorized change\n"

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_write_text_file_tool(store, str(task["id"]))
    result = invoke_tool(tool, payload)

    assert "does not match the exact verified request" in result
    assert fake_engine.calls == []


def test_modified_expected_sha256_invalidates_full_write_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    approval_row = approve(store, request)

    payload = valid_payload(str(approval_row["id"]), request)
    payload["expected_sha256"] = "b" * 64

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_write_text_file_tool(store, str(task["id"]))
    result = invoke_tool(tool, payload)

    assert "does not match the exact verified request" in result
    assert fake_engine.calls == []


def test_outside_sandbox_full_write_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_write_text_file_tool(store, str(task["id"]))

    result = invoke_tool(
        tool,
        {
            "approval_id": "unused",
            "path": r"D:\AI-Agent-Command-Center\agent.py",
            "repository_path": SANDBOX,
            "content": "blocked",
            "expected_sha256": "a" * 64,
        },
    )

    assert "restricted to" in result
    assert fake_engine.calls == []


def test_nonexistent_file_creation_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_write_text_file_tool(store, str(task["id"]))

    result = invoke_tool(
        tool,
        {
            "approval_id": "unused",
            "path": rf"{SANDBOX}\does-not-exist.py",
            "repository_path": SANDBOX,
            "content": "print('blocked')\n",
            "expected_sha256": "a" * 64,
        },
    )

    assert "existing files only" in result
    assert fake_engine.calls == []


def test_invalid_expected_sha256_is_rejected_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_write_text_file_tool(store, str(task["id"]))

    result = invoke_tool(
        tool,
        {
            "approval_id": "unused",
            "path": APP_PATH,
            "repository_path": SANDBOX,
            "content": current_app_text(),
            "expected_sha256": "not-a-sha256",
        },
    )

    assert "64-character hexadecimal SHA256" in result
    assert fake_engine.calls == []
