from __future__ import annotations

import json
from pathlib import Path

from store import TaskStore


def _store(tmp_path: Path) -> TaskStore:
    store = TaskStore(
        db_path=tmp_path / "task-state.db",
        audit_log_path=tmp_path / "audit.jsonl",
    )
    store.seed_defaults()
    return store


def test_fail_task_persists_diagnostics_and_clears_completed_timestamp(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    task = store.create_task(
        title="State integrity failure transition",
        description="Test failed transition cleanup.",
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="none",
        requires_approval=False,
    )

    store.complete_task(
        str(task["id"]),
        {"output": "success"},
    )

    store.fail_task(
        str(task["id"]),
        "Later failure",
    )

    current = store.get_task(str(task["id"]))

    assert current is not None
    assert current["status"] == "failed"
    assert current["error"] == "Later failure"
    assert current["failure_code"] == "TASK_EXECUTION_FAILED"
    assert json.loads(current["diagnostics_json"]) == {}
    assert json.loads(current["result_json"]) == {
        "status": "failed",
        "summary": "Later failure",
        "failure_code": "TASK_EXECUTION_FAILED",
        "diagnostics": {},
    }
    assert current["completed_at"] is None


def test_complete_task_clears_prior_error(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    task = store.create_task(
        title="State integrity completion transition",
        description="Test completed transition cleanup.",
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="none",
        requires_approval=False,
    )

    store.fail_task(
        str(task["id"]),
        "Initial failure",
    )

    store.complete_task(
        str(task["id"]),
        {"output": "recovered"},
    )

    current = store.get_task(str(task["id"]))

    assert current is not None
    assert current["status"] == "completed"
    assert current["error"] is None
    assert current["failure_code"] is None
    assert current["diagnostics_json"] is None
    assert current["result_json"] is not None
    assert current["completed_at"] is not None


def test_seed_defaults_records_initialization_activity_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.seed_defaults()
    store.seed_defaults()

    activity = store.list_activity(limit=10)
    initialized = [
        item
        for item in activity
        if item["event_type"] == "system"
        and item["message"] == "Command Center initialized"
    ]

    assert len(initialized) == 1


def test_recover_interrupted_tasks_requeues_side_effect_free_work(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    task = store.create_task(
        title="Interrupted read-only task",
        description="Recover this task after a server restart.",
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="none",
        requires_approval=False,
    )

    claimed = store.claim_next_task()
    assert claimed is not None
    assert claimed["id"] == task["id"]

    recovered = store.recover_interrupted_tasks()

    current = store.get_task(str(task["id"]))
    assert current is not None
    assert current["status"] == "queued"
    assert current["started_at"] is None
    assert current["error"] is None
    assert current["failure_code"] is None
    assert current["diagnostics_json"] is None
    assert current["result_json"] is None
    assert [item["id"] for item in recovered] == [task["id"]]

    activity = store.list_activity(limit=5)
    assert any(
        item["event_type"] == "task.requeued"
        and item["task_id"] == task["id"]
        for item in activity
    )


def test_recover_interrupted_tasks_blocks_side_effecting_work(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    task = store.create_task(
        title="Interrupted external task",
        description="Do not retry this automatically.",
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="external",
        requires_approval=True,
        defer_exact_approval=True,
    )

    with store._lock, store._connect() as db:
        db.execute(
            "UPDATE tasks SET status='running', started_at=?, updated_at=? WHERE id=?",
            ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", task["id"]),
        )

    recovered = store.recover_interrupted_tasks()

    current = store.get_task(str(task["id"]))
    assert current is not None
    assert current["status"] == "blocked"
    assert current["started_at"] is None
    assert "Manual review is required" in current["error"]
    assert current["failure_code"] == "RESTART_REVIEW_REQUIRED"
    assert json.loads(current["diagnostics_json"]) == {
        "reason": "server_restart",
        "side_effect_level": "external",
    }
    assert json.loads(current["result_json"])["failure_code"] == (
        "RESTART_REVIEW_REQUIRED"
    )
    assert [item["id"] for item in recovered] == [task["id"]]
