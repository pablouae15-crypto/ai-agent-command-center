from __future__ import annotations

from pathlib import Path

from store import TaskStore


def _store(tmp_path: Path) -> TaskStore:
    store = TaskStore(
        db_path=tmp_path / "task-state.db",
        audit_log_path=tmp_path / "audit.jsonl",
    )
    store.seed_defaults()
    return store


def test_fail_task_clears_prior_result_and_completed_timestamp(
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
    assert current["result_json"] is None
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
    assert current["result_json"] is not None
    assert current["completed_at"] is not None
