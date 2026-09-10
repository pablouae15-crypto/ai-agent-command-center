from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import runtime as runtime_module
from runtime import Runtime
from store import TaskStore


def test_specialist_refusal_is_not_marked_completed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = TaskStore(
        db_path=tmp_path / "runtime-outcomes.db",
        audit_log_path=tmp_path / "audit.jsonl",
    )
    store.seed_defaults()

    task = store.create_task(
        title="Specialist refusal test",
        description="Perform work that the specialist cannot execute.",
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="none",
        requires_approval=False,
    )

    async def fake_run_specialist(*args, **kwargs):
        return (
            "I can’t perform the requested action because the required "
            "authorization is unavailable. No changes were made."
        )

    monkeypatch.setattr(
        runtime_module,
        "run_specialist",
        fake_run_specialist,
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

    current = store.get_task(str(task["id"]))

    assert current is not None
    assert current["status"] == "failed"
    assert current["error"] is not None
    assert "No changes were made" in current["error"]


def test_live_refusal_wording_is_not_marked_completed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = TaskStore(
        db_path=tmp_path / "runtime-live-refusal.db",
        audit_log_path=tmp_path / "audit-live-refusal.jsonl",
    )
    store.seed_defaults()

    task = store.create_task(
        title="Live refusal wording test",
        description="Attempt a verified edit without usable approval context.",
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="none",
        requires_approval=False,
    )

    async def fake_run_specialist(*args, **kwargs):
        return (
            "Cannot perform the edit: the current context has no approval "
            "record or valid approval ID for this request. "
            "No files were inspected or changed, and sandbox_pytest was not run."
        )

    monkeypatch.setattr(
        runtime_module,
        "run_specialist",
        fake_run_specialist,
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

    current = store.get_task(str(task["id"]))

    assert current is not None
    assert current["status"] == "failed"
    assert current["error"] is not None
    assert "No files were inspected or changed" in current["error"]
