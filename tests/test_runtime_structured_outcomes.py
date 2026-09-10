from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import runtime as runtime_module
from agent import SpecialistOutcome
from runtime import Runtime
from store import TaskStore


def _settings():
    return SimpleNamespace(
        enable_agent_runs=True,
        worker_poll_seconds=0.01,
        scheduler_poll_seconds=3600,
        openai_model="unused",
    )


def _run_until_terminal(runtime: Runtime, store: TaskStore, task_id: str) -> None:
    async def runner():
        worker = asyncio.create_task(runtime._worker_loop())

        for _ in range(100):
            current = store.get_task(task_id)

            if current["status"] in {
                "completed",
                "failed",
            }:
                break

            await asyncio.sleep(0.01)

        runtime._stop.set()

        try:
            await asyncio.wait_for(worker, timeout=1)
        except asyncio.CancelledError:
            pass

    asyncio.run(runner())


def test_structured_completed_outcome_completes_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = TaskStore(
        db_path=tmp_path / "structured-completed.db",
        audit_log_path=tmp_path / "audit-completed.jsonl",
    )
    store.seed_defaults()

    task = store.create_task(
        title="Structured completed outcome",
        description="Test structured completed outcome.",
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="none",
        requires_approval=False,
    )

    async def fake_run_specialist(*args, **kwargs):
        return SpecialistOutcome(
            status="completed",
            summary="Work completed.",
            evidence=["verification passed"],
        )

    monkeypatch.setattr(
        runtime_module,
        "run_specialist",
        fake_run_specialist,
    )

    runtime = Runtime(store, _settings())

    _run_until_terminal(
        runtime,
        store,
        str(task["id"]),
    )

    current = store.get_task(str(task["id"]))

    assert current is not None
    assert current["status"] == "completed"
    assert current["error"] is None
    assert current["result_json"] is not None


def test_structured_failed_outcome_fails_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = TaskStore(
        db_path=tmp_path / "structured-failed.db",
        audit_log_path=tmp_path / "audit-failed.jsonl",
    )
    store.seed_defaults()

    task = store.create_task(
        title="Structured failed outcome",
        description="Test structured failed outcome.",
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="none",
        requires_approval=False,
    )

    async def fake_run_specialist(*args, **kwargs):
        return SpecialistOutcome(
            status="failed",
            summary="Verification failed.",
            evidence=["pytest failed"],
        )

    monkeypatch.setattr(
        runtime_module,
        "run_specialist",
        fake_run_specialist,
    )

    runtime = Runtime(store, _settings())

    _run_until_terminal(
        runtime,
        store,
        str(task["id"]),
    )

    current = store.get_task(str(task["id"]))

    assert current is not None
    assert current["status"] == "failed"
    assert current["error"] is not None
    assert "Verification failed" in current["error"]


def test_structured_blocked_outcome_sets_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = TaskStore(
        db_path=tmp_path / "structured-blocked.db",
        audit_log_path=tmp_path / "audit-blocked.jsonl",
    )
    store.seed_defaults()

    task = store.create_task(
        title="Structured blocked outcome",
        description="Test structured blocked outcome.",
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="none",
        requires_approval=False,
    )

    async def fake_run_specialist(*args, **kwargs):
        return SpecialistOutcome(
            status="blocked",
            summary="Approval is required.",
            evidence=[],
        )

    monkeypatch.setattr(
        runtime_module,
        "run_specialist",
        fake_run_specialist,
    )

    runtime = Runtime(store, _settings())

    _run_until_terminal(
        runtime,
        store,
        str(task["id"]),
    )

    current = store.get_task(str(task["id"]))

    assert current is not None
    assert current["status"] == "blocked"
    assert current["error"] == "Approval is required."


def test_structured_partial_outcome_sets_partial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = TaskStore(
        db_path=tmp_path / "structured-partial.db",
        audit_log_path=tmp_path / "audit-partial.jsonl",
    )
    store.seed_defaults()

    task = store.create_task(
        title="Structured partial outcome",
        description="Test structured partial outcome.",
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="none",
        requires_approval=False,
    )

    async def fake_run_specialist(*args, **kwargs):
        return SpecialistOutcome(
            status="partial",
            summary="Inspection completed; implementation incomplete.",
            evidence=["repository inspected"],
        )

    monkeypatch.setattr(
        runtime_module,
        "run_specialist",
        fake_run_specialist,
    )

    runtime = Runtime(store, _settings())

    _run_until_terminal(
        runtime,
        store,
        str(task["id"]),
    )

    current = store.get_task(str(task["id"]))

    assert current is not None
    assert current["status"] == "partial"
    assert current["error"] == (
        "Inspection completed; implementation incomplete."
    )
    assert current["result_json"] is not None
