from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import runtime as runtime_module
from runtime import Runtime
from store import TaskStore
from write_approval import (
    VerifiedEditBatchRequest,
    VerifiedEditOperation,
    VerifiedEditRequest,
)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        enable_agent_runs=True,
        worker_poll_seconds=0.01,
        scheduler_poll_seconds=3600,
        openai_model="unused",
    )


def _run_worker(store: TaskStore, task_id: str) -> dict:
    async def run() -> None:
        runtime = Runtime(store, _settings())
        worker = asyncio.create_task(runtime._worker_loop())
        try:
            for _ in range(100):
                task = store.get_task(task_id)
                if task is not None and task["status"] in {"completed", "failed"}:
                    return
                await asyncio.sleep(0.01)
        finally:
            runtime._stop.set()
            await asyncio.wait_for(worker, timeout=1)

    asyncio.run(run())
    task = store.get_task(task_id)
    assert task is not None
    return task


def _store(tmp_path: Path, name: str) -> TaskStore:
    store = TaskStore(
        db_path=tmp_path / f"{name}.db",
        audit_log_path=tmp_path / f"{name}.jsonl",
    )
    store.seed_defaults()
    return store


def _approve_task(store: TaskStore, task_id: str) -> None:
    task = store.get_task(task_id)
    assert task is not None
    store.decide_approval(
        str(task["approval_id"]),
        "approved",
        decided_by="runtime-regression-test",
    )


def _blocked_stage(
    store: TaskStore,
    parent_id: str,
    *,
    new_text: str = "return a - b",
) -> dict:
    stage = store.create_task(
        title="Stage 1: Developer",
        description="Inspect the sandbox and identify the exact fix.",
        agent_name="Developer",
        priority="High",
        parent_task_id=parent_id,
        workflow_id=parent_id,
        stage_index=1,
        workflow_managed=True,
    )
    store.start_workflow_stage(str(stage["id"]))
    store.finish_workflow_stage(
        str(stage["id"]),
        status="blocked",
        result={
            "summary": "An exact approval is required.",
            "evidence": ["The proposed edit is waiting for approval."],
            "exact_edit_proposal": {
                "capability": "replace_text",
                "path": r"D:\Shared-Local-Execution-Engine-Sandbox\app.py",
                "old_text": "return a + b",
                "new_text": new_text,
                "expected_replacements": 1,
            },
        },
    )
    return stage


def _single_request(task_id: str, *, new_text: str) -> VerifiedEditRequest:
    return VerifiedEditRequest(
        task_id=task_id,
        capability="replace_text",
        path=r"D:\Shared-Local-Execution-Engine-Sandbox\app.py",
        repository_path=r"D:\Shared-Local-Execution-Engine-Sandbox",
        verification_profile="sandbox_pytest",
        old_text="return a + b",
        new_text=new_text,
        expected_replacements=1,
    )


def test_approved_generic_task_completes_without_workflow_match_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _store(tmp_path, "generic")
    task = store.create_task(
        title="Approved generic task",
        description="Perform a read-only specialist task.",
        agent_name="QA",
        priority="Medium",
        side_effect_level="external",
        requires_approval=True,
    )
    _approve_task(store, str(task["id"]))
    calls = []

    async def fake_run_specialist(task_arg, model, store_arg):
        calls.append(str(task_arg["id"]))
        return "generic specialist completed"

    monkeypatch.setattr(runtime_module, "run_specialist", fake_run_specialist)
    completed = _run_worker(store, str(task["id"]))

    assert completed["status"] == "completed"
    assert json.loads(completed["result_json"])["output"] == (
        "generic specialist completed"
    )
    assert calls == [str(task["id"])]


def test_generic_approval_does_not_resume_a_blocked_workflow_stage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _store(tmp_path, "generic-with-stage")
    task = store.create_task(
        title="Approved generic workflow parent",
        description="Continue the workflow with a generic specialist result.",
        agent_name="Orchestrator",
        priority="High",
        side_effect_level="external",
        requires_approval=True,
    )
    stage = _blocked_stage(store, str(task["id"]))
    _approve_task(store, str(task["id"]))

    async def fake_run_specialist(task_arg, model, store_arg):
        return "generic parent completed"

    monkeypatch.setattr(runtime_module, "run_specialist", fake_run_specialist)
    completed = _run_worker(store, str(task["id"]))

    assert completed["status"] == "completed"
    persisted_stage = store.get_task(str(stage["id"]))
    assert persisted_stage is not None
    assert persisted_stage["status"] == "blocked"


def test_approved_single_edit_with_unmatched_stage_completes_parent_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _store(tmp_path, "single-unmatched-stage")
    task = store.create_task(
        title="Approved single edit",
        description="Apply the exact approved edit.",
        agent_name="Developer",
        priority="High",
        side_effect_level="external",
        requires_approval=False,
    )
    stage = _blocked_stage(store, str(task["id"]), new_text="return a * b")
    request = _single_request(str(task["id"]), new_text="return a + 1")
    pending = store.create_exact_approval(request)
    store.decide_approval(
        str(pending["id"]),
        "approved",
        decided_by="runtime-regression-test",
    )
    calls = []

    def fake_execute(**kwargs):
        calls.append(kwargs)
        return {"status": "verified", "verified": True}

    monkeypatch.setattr(runtime_module, "execute_approved_verified_edit", fake_execute)

    async def forbidden_run_specialist(*args, **kwargs):
        raise AssertionError("An approved exact edit must bypass the specialist.")

    monkeypatch.setattr(runtime_module, "run_specialist", forbidden_run_specialist)
    completed = _run_worker(store, str(task["id"]))

    assert completed["status"] == "completed"
    persisted_stage = store.get_task(str(stage["id"]))
    assert persisted_stage is not None
    assert persisted_stage["status"] == "blocked"
    assert len(calls) == 1
    assert calls[0]["approval_id"] == str(pending["id"])


def test_approved_batch_edit_without_workflow_stage_completes_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _store(tmp_path, "batch-no-stage")
    task = store.create_task(
        title="Approved batch edit",
        description="Apply the exact approved multi-file edit.",
        agent_name="Developer",
        priority="High",
        side_effect_level="external",
        requires_approval=False,
    )
    edits = (
        VerifiedEditOperation(
            path=r"D:\Shared-Local-Execution-Engine-Sandbox\app.py",
            old_text="return a + b",
            new_text="return a - b",
            expected_replacements=1,
        ),
        VerifiedEditOperation(
            path=r"D:\Shared-Local-Execution-Engine-Sandbox\test_app.py",
            old_text="assert add(2, 3) == 5",
            new_text="assert add(2, 3) == -1",
            expected_replacements=1,
        ),
    )
    request = VerifiedEditBatchRequest(
        task_id=str(task["id"]),
        capability="replace_text_batch",
        repository_path=r"D:\Shared-Local-Execution-Engine-Sandbox",
        verification_profile="sandbox_pytest",
        edits=edits,
    )
    pending = store.create_exact_approval(request)
    store.decide_approval(
        str(pending["id"]),
        "approved",
        decided_by="runtime-regression-test",
    )
    calls = []

    def fake_execute(**kwargs):
        calls.append(kwargs)
        return {"status": "verified", "verified": True}

    monkeypatch.setattr(
        runtime_module,
        "execute_approved_verified_edit_batch",
        fake_execute,
    )
    completed = _run_worker(store, str(task["id"]))

    assert completed["status"] == "completed"
    result = json.loads(completed["result_json"])
    assert result["output"]["status"] == "completed"
    assert "test_app.py" in result["output"]["evidence"][0]
    assert len(calls) == 1
    assert calls[0]["approval_id"] == str(pending["id"])
    assert calls[0]["edits"] == [
        {
            "path": edit.path,
            "old_text": edit.old_text,
            "new_text": edit.new_text,
            "expected_replacements": edit.expected_replacements,
        }
        for edit in edits
    ]


def test_approved_batch_edit_resumes_only_the_matching_blocked_stage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _store(tmp_path, "batch-matching-stage")
    task = store.create_task(
        title="Approved batch workflow parent",
        description="Apply the exact approved batch and continue the workflow.",
        agent_name="Orchestrator",
        priority="High",
        side_effect_level="none",
        requires_approval=False,
    )
    unmatched = _blocked_stage(store, str(task["id"]), new_text="return a * b")
    matching = store.create_task(
        title="Stage 2: Developer",
        description="Apply the exact multi-file edit.",
        agent_name="Developer",
        priority="High",
        parent_task_id=str(task["id"]),
        workflow_id=str(task["id"]),
        stage_index=2,
        workflow_managed=True,
    )
    edits = (
        VerifiedEditOperation(
            path=r"D:\Shared-Local-Execution-Engine-Sandbox\app.py",
            old_text="return a + b",
            new_text="return a - b",
            expected_replacements=1,
        ),
        VerifiedEditOperation(
            path=r"D:\Shared-Local-Execution-Engine-Sandbox\test_app.py",
            old_text="assert add(2, 3) == 5",
            new_text="assert add(2, 3) == -1",
            expected_replacements=1,
        ),
    )
    store.start_workflow_stage(str(matching["id"]))
    store.finish_workflow_stage(
        str(matching["id"]),
        status="blocked",
        result={
            "summary": "The exact batch approval is required.",
            "evidence": ["Both files are ready for the approved edit."],
            "exact_edit_batch_proposal": {
                "capability": "replace_text_batch",
                "edits": [
                    {
                        "path": edit.path,
                        "old_text": edit.old_text,
                        "new_text": edit.new_text,
                        "expected_replacements": edit.expected_replacements,
                    }
                    for edit in edits
                ],
            },
        },
    )
    request = VerifiedEditBatchRequest(
        task_id=str(task["id"]),
        capability="replace_text_batch",
        repository_path=r"D:\Shared-Local-Execution-Engine-Sandbox",
        verification_profile="sandbox_pytest",
        edits=edits,
    )
    pending = store.create_exact_approval(request)
    store.decide_approval(
        str(pending["id"]),
        "approved",
        decided_by="runtime-regression-test",
    )

    def fake_execute(**kwargs):
        return {"status": "verified", "verified": True}

    monkeypatch.setattr(
        runtime_module,
        "execute_approved_verified_edit_batch",
        fake_execute,
    )

    async def fake_run_specialist(task_arg, model, store_arg):
        return runtime_module.SpecialistOutcome(
            status="completed",
            summary="The workflow continued after the approved batch.",
            evidence=["The following stage ran."],
        )

    monkeypatch.setattr(runtime_module, "run_specialist", fake_run_specialist)
    completed = _run_worker(store, str(task["id"]))

    assert completed["status"] == "completed"
    unmatched_after = store.get_task(str(unmatched["id"]))
    matching_after = store.get_task(str(matching["id"]))
    assert unmatched_after is not None
    assert matching_after is not None
    assert unmatched_after["status"] == "blocked"
    assert matching_after["status"] == "completed"
