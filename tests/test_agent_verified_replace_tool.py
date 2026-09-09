from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agents.tool_context import ToolContext

import agent
from agent import build_verified_replace_text_tool
from engine.approvals import ApprovalRecord
from store import TaskStore
from write_approval import VerifiedEditRequest


SANDBOX = r"D:\Shared-Local-Execution-Engine-Sandbox"
APP_PATH = rf"{SANDBOX}\app.py"
OTHER_PATH = rf"{SANDBOX}\other.py"


def make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(
        db_path=tmp_path / "command-center.db",
        audit_log_path=tmp_path / "audit.jsonl",
    )


def make_task(store: TaskStore) -> dict[str, object]:
    return store.create_task(
        title="FunctionTool verified edit",
        description="Test approval-gated verified replacement wrapper.",
        agent_name="Orchestrator",
        requires_approval=False,
    )


def make_request(
    task_id: str,
    *,
    path: str = APP_PATH,
    old_text: str = "return a + b",
    new_text: str = "return (a + b)",
    expected_replacements: int = 1,
) -> VerifiedEditRequest:
    return VerifiedEditRequest(
        task_id=task_id,
        capability="replace_text",
        path=path,
        repository_path=SANDBOX,
        verification_profile="sandbox_pytest",
        old_text=old_text,
        new_text=new_text,
        expected_replacements=expected_replacements,
    )


def approve(
    store: TaskStore,
    request: VerifiedEditRequest,
) -> dict[str, object]:
    pending = store.create_exact_approval(request)
    return store.decide_approval(
        str(pending["id"]),
        "approved",
        decided_by="test-user",
    )


def invoke_tool(
    tool,
    payload: dict[str, object],
) -> str:
    serialized = json.dumps(payload)

    context = ToolContext(
        context=None,
        tool_name="verified_replace_text",
        tool_call_id="test-tool-call",
        tool_arguments=serialized,
    )

    async def run() -> str:
        return await tool.on_invoke_tool(context, serialized)

    return asyncio.run(run())


class FakeExecutionEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def verified_replace_text(
        self,
        path,
        old_text,
        new_text,
        *,
        repository_path,
        verification_profile,
        task_id,
        approval,
        expected_replacements=1,
        **kwargs,
    ):
        self.calls.append(
            {
                "path": path,
                "old_text": old_text,
                "new_text": new_text,
                "repository_path": repository_path,
                "verification_profile": verification_profile,
                "task_id": task_id,
                "approval": approval,
                "expected_replacements": expected_replacements,
            }
        )

        return {
            "status": "verified",
            "verified": True,
        }


def valid_payload(approval_id: str) -> dict[str, object]:
    return {
        "approval_id": approval_id,
        "path": APP_PATH,
        "repository_path": SANDBOX,
        "old_text": "return a + b",
        "new_text": "return (a + b)",
        "expected_replacements": 1,
    }


def test_exact_approved_request_reaches_execution_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    approval_row = approve(store, request)

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_replace_text_tool(store, str(task["id"]))
    result = invoke_tool(tool, valid_payload(str(approval_row["id"])))

    assert "verified" in result
    assert len(fake_engine.calls) == 1

    call = fake_engine.calls[0]
    assert call["task_id"] == task["id"]
    assert call["path"] == APP_PATH
    assert call["repository_path"] == SANDBOX
    assert call["verification_profile"] == "sandbox_pytest"
    assert call["expected_replacements"] == 1
    assert isinstance(call["approval"], ApprovalRecord)


def test_pending_approval_is_denied_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    pending = store.create_exact_approval(request)

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_replace_text_tool(store, str(task["id"]))

    result = invoke_tool(tool, valid_payload(str(pending["id"])))

    assert "Approval is not approved" in result
    assert fake_engine.calls == []


def test_unknown_approval_id_is_denied_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_replace_text_tool(store, str(task["id"]))

    result = invoke_tool(tool, valid_payload("missing-approval"))

    assert "approval" in result.lower()
    assert fake_engine.calls == []


def test_modified_new_text_invalidates_exact_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    approval_row = approve(store, request)

    payload = valid_payload(str(approval_row["id"]))
    payload["new_text"] = "return a - b"

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_replace_text_tool(store, str(task["id"]))

    result = invoke_tool(tool, payload)

    assert "error occurred while running the tool" in result.lower()
    assert fake_engine.calls == []


def test_modified_path_invalidates_exact_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    approval_row = approve(store, request)

    payload = valid_payload(str(approval_row["id"]))
    payload["path"] = OTHER_PATH

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_replace_text_tool(store, str(task["id"]))

    result = invoke_tool(tool, payload)

    assert "error occurred while running the tool" in result.lower()
    assert fake_engine.calls == []


def test_outside_sandbox_path_is_denied_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)

    payload = valid_payload("unused-approval")
    payload["path"] = r"D:\AI-Agent-Command-Center\agent.py"

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_replace_text_tool(store, str(task["id"]))

    result = invoke_tool(tool, payload)

    assert "error occurred while running the tool" in result.lower()
    assert fake_engine.calls == []


def test_wrong_repository_path_is_denied_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)

    payload = valid_payload("unused-approval")
    payload["repository_path"] = r"D:\AI-Agent-Command-Center"

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_replace_text_tool(store, str(task["id"]))

    result = invoke_tool(tool, payload)

    assert "error occurred while running the tool" in result.lower()
    assert fake_engine.calls == []


def test_invalid_expected_replacement_count_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)

    payload = valid_payload("unused-approval")
    payload["expected_replacements"] = 0

    fake_engine = FakeExecutionEngine()
    monkeypatch.setattr(agent, "execution_engine", fake_engine)

    tool = build_verified_replace_text_tool(store, str(task["id"]))

    result = invoke_tool(tool, payload)

    assert "expected_replacements must be at least 1" in result
    assert fake_engine.calls == []
