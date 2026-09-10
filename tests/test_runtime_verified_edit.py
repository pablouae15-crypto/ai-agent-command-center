from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import runtime as runtime_module
from runtime import Runtime
from store import TaskStore
from write_approval import VerifiedEditRequest


def test_approved_verified_edit_runtime_bypasses_llm(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = TaskStore(
        db_path=tmp_path / "runtime-verified-edit.db",
        audit_log_path=tmp_path / "audit.jsonl",
    )

    store.seed_defaults()

    task = store.create_task(
        title="Runtime verified edit test",
        description="Execute exact approved sandbox edit.",
        agent_name="Developer",
        priority="Medium",
        side_effect_level="external",
        requires_approval=False,
    )

    request = VerifiedEditRequest(
        task_id=str(task["id"]),
        capability="replace_text",
        path=r"D:\Shared-Local-Execution-Engine-Sandbox\app.py",
        repository_path=r"D:\Shared-Local-Execution-Engine-Sandbox",
        verification_profile="sandbox_pytest",
        old_text="return a + b",
        new_text="return (a + b)",
        expected_replacements=1,
    )

    pending = store.create_exact_approval(
        request,
        reason="Execute this exact verified edit",
    )

    store.decide_approval(
        str(pending["id"]),
        "approved",
        decided_by="runtime-test-user",
    )

    calls = []

    def fake_execute_approved_verified_edit(
        *,
        store,
        task_id,
        approval_id,
        path,
        repository_path,
        old_text,
        new_text,
        expected_replacements,
    ):
        calls.append(
            {
                "task_id": task_id,
                "approval_id": approval_id,
                "path": path,
                "repository_path": repository_path,
                "old_text": old_text,
                "new_text": new_text,
                "expected_replacements": expected_replacements,
            }
        )

        return "verified-edit-success"

    monkeypatch.setattr(
        runtime_module,
        "execute_approved_verified_edit",
        fake_execute_approved_verified_edit,
    )

    async def forbidden_run_specialist(*args, **kwargs):
        raise AssertionError(
            "LLM specialist must not run for approved verified edit."
        )

    monkeypatch.setattr(
        runtime_module,
        "run_specialist",
        forbidden_run_specialist,
    )

    settings = SimpleNamespace(
        enable_agent_runs=True,
        worker_poll_seconds=0.01,
        scheduler_poll_seconds=3600,
        openai_model="unused",
    )

    runtime = Runtime(
        store,
        settings,
    )

    async def run_worker():
        worker = asyncio.create_task(
            runtime._worker_loop()
        )

        for _ in range(100):
            current = store.get_task(
                str(task["id"])
            )

            if current["status"] in {
                "completed",
                "failed",
            }:
                break

            await asyncio.sleep(0.01)

        runtime._stop.set()

        try:
            await asyncio.wait_for(
                worker,
                timeout=1,
            )
        except asyncio.CancelledError:
            pass

    asyncio.run(run_worker())

    completed = store.get_task(
        str(task["id"])
    )

    assert completed is not None
    assert completed["status"] == "completed"

    assert len(calls) == 1

    call = calls[0]

    assert call["task_id"] == str(task["id"])
    assert call["approval_id"] == str(pending["id"])

    assert (
        call["path"]
        == r"D:\Shared-Local-Execution-Engine-Sandbox\app.py"
    )

    assert (
        call["repository_path"]
        == r"D:\Shared-Local-Execution-Engine-Sandbox"
    )

    assert call["old_text"] == "return a + b"
    assert call["new_text"] == "return (a + b)"
    assert call["expected_replacements"] == 1



def test_approved_verified_edit_runtime_marks_rollback_as_failed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = TaskStore(
        db_path=tmp_path / "runtime-verified-edit-failure.db",
        audit_log_path=tmp_path / "audit-failure.jsonl",
    )

    store.seed_defaults()

    task = store.create_task(
        title="Runtime verified edit rollback test",
        description="Execute exact approved sandbox edit that rolls back.",
        agent_name="Developer",
        priority="Medium",
        side_effect_level="external",
        requires_approval=False,
    )

    request = VerifiedEditRequest(
        task_id=str(task["id"]),
        capability="replace_text",
        path=r"D:\Shared-Local-Execution-Engine-Sandbox\app.py",
        repository_path=r"D:\Shared-Local-Execution-Engine-Sandbox",
        verification_profile="sandbox_pytest",
        old_text="return a + b",
        new_text="return a - b",
        expected_replacements=1,
    )

    pending = store.create_exact_approval(
        request,
        reason="Execute this exact verified edit",
    )

    store.decide_approval(
        str(pending["id"]),
        "approved",
        decided_by="runtime-test-user",
    )

    def fake_execute_approved_verified_edit(**kwargs):
        return (
            "{'status': 'rolled_back', "
            "'verified': False, "
            "'rollback': {'restored': True}}"
        )

    monkeypatch.setattr(
        runtime_module,
        "execute_approved_verified_edit",
        fake_execute_approved_verified_edit,
    )

    async def forbidden_run_specialist(*args, **kwargs):
        raise AssertionError(
            "LLM specialist must not run for approved verified edit."
        )

    monkeypatch.setattr(
        runtime_module,
        "run_specialist",
        forbidden_run_specialist,
    )

    settings = SimpleNamespace(
        enable_agent_runs=True,
        worker_poll_seconds=0.01,
        scheduler_poll_seconds=3600,
        openai_model="unused",
    )

    runtime = Runtime(
        store,
        settings,
    )

    async def run_worker():
        worker = asyncio.create_task(
            runtime._worker_loop()
        )

        for _ in range(100):
            current = store.get_task(
                str(task["id"])
            )

            if current["status"] in {
                "completed",
                "failed",
            }:
                break

            await asyncio.sleep(0.01)

        runtime._stop.set()

        try:
            await asyncio.wait_for(
                worker,
                timeout=1,
            )
        except asyncio.CancelledError:
            pass

    asyncio.run(run_worker())

    failed = store.get_task(
        str(task["id"])
    )

    assert failed is not None
    assert failed["status"] == "failed"
    assert "rolled_back" in str(failed["error"])
    assert "verified" in str(failed["error"])


def test_runtime_promotes_approved_generic_edit_to_exact_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = TaskStore(
        db_path=tmp_path / "runtime-generic-to-exact.db",
        audit_log_path=tmp_path / "audit-generic-to-exact.jsonl",
    )

    store.seed_defaults()

    task = store.create_task(
        title="Sandbox verified edit",
        description=(
            'In D:\\Shared-Local-Execution-Engine-Sandbox\\app.py, '
            'replace exactly "return a + b" with "return a - b". '
            'Use the approved verified replace_text workflow with '
            'repository path D:\\Shared-Local-Execution-Engine-Sandbox '
            'and sandbox_pytest verification. '
            'Do not make any other changes.'
        ),
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="external",
        requires_approval=True,
    )

    generic = store.ensure_approval(str(task["id"]))

    store.decide_approval(
        str(generic["id"]),
        "approved",
        decided_by="runtime-test-user",
    )

    async def forbidden_run_specialist(*args, **kwargs):
        raise AssertionError(
            "LLM specialist must not run before exact approval is created."
        )

    monkeypatch.setattr(
        runtime_module,
        "run_specialist",
        forbidden_run_specialist,
    )

    settings = SimpleNamespace(
        enable_agent_runs=True,
        worker_poll_seconds=0.01,
        scheduler_poll_seconds=3600,
        openai_model="unused",
    )

    runtime = Runtime(
        store,
        settings,
    )

    async def run_worker():
        worker = asyncio.create_task(
            runtime._worker_loop()
        )

        for _ in range(100):
            current = store.get_task(
                str(task["id"])
            )

            if (
                current is not None
                and current["status"] == "awaiting_approval"
                and current["approval_id"] != generic["id"]
            ):
                break

            await asyncio.sleep(0.01)

        runtime._stop.set()

        try:
            await asyncio.wait_for(
                worker,
                timeout=1,
            )
        except asyncio.CancelledError:
            pass

    asyncio.run(run_worker())

    current = store.get_task(
        str(task["id"])
    )

    assert current is not None
    assert current["status"] == "awaiting_approval"
    assert current["approval_id"] != generic["id"]

    exact = store.get_approval(
        str(current["approval_id"])
    )

    assert exact is not None
    assert exact["status"] == "pending"

    import json

    payload = json.loads(
        exact["display_payload_json"]
    )

    assert payload == {
        "type": "verified_edit_execution",
        "capability": "replace_text",
        "path": r"D:\Shared-Local-Execution-Engine-Sandbox\app.py",
        "repository_path": r"D:\Shared-Local-Execution-Engine-Sandbox",
        "verification_profile": "sandbox_pytest",
        "old_text": "return a + b",
        "new_text": "return a - b",
        "expected_replacements": 1,
    }

    old_generic = store.get_approval(
        str(generic["id"])
    )

    assert old_generic is not None
    assert old_generic["status"] == "superseded"
