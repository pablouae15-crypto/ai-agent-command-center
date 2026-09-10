from pathlib import Path

import pytest

from store import TaskStore


def make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(
        tmp_path / "command_center.db",
        tmp_path / "audit.jsonl",
    )


def set_task_status(store: TaskStore, task_id: str, status: str) -> None:
    with store._connect() as db:
        db.execute(
            "UPDATE tasks SET status=? WHERE id=?",
            (status, task_id),
        )


def test_archive_task_hides_task_from_default_list_and_summary(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    task = store.create_task(
        title="Old blocked task",
        description="Old blocked task for cleanup.",
        agent_name="Orchestrator",
        priority="Medium",
    )
    set_task_status(store, str(task["id"]), "blocked")

    archived = store.archive_task(str(task["id"]))

    assert archived is not None
    assert archived["archived_at"] is not None

    visible_ids = {row["id"] for row in store.list_tasks()}
    all_ids = {row["id"] for row in store.list_tasks(include_archived=True)}

    assert task["id"] not in visible_ids
    assert task["id"] in all_ids
    assert store.summary()["archived_tasks"] == 1


def test_archive_task_rejects_active_task(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    task = store.create_task(
        title="Active task",
        description="Active task must not be archived.",
        agent_name="Orchestrator",
        priority="Medium",
    )

    with pytest.raises(PermissionError):
        store.archive_task(str(task["id"]))


def test_archive_task_returns_none_for_missing_task(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    assert store.archive_task("missing-task") is None
