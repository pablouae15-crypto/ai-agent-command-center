from pathlib import Path

from fastapi.testclient import TestClient

import main
from store import TaskStore


def make_store(tmp_path: Path) -> TaskStore:
    store = TaskStore(
        tmp_path / "command_center.db",
        tmp_path / "audit.jsonl",
    )
    store.seed_defaults()
    return store


def test_tasks_endpoint_returns_visible_tasks_ordered_by_priority(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    low = test_store.create_task(
        title="Low priority visible task",
        description="Visible low priority task.",
        agent_name="Orchestrator",
        priority="Low",
    )
    critical = test_store.create_task(
        title="Critical visible task",
        description="Visible critical task.",
        agent_name="Orchestrator",
        priority="Critical",
    )
    archived = test_store.create_task(
        title="Archived hidden task",
        description="Archived task should not be returned.",
        agent_name="Orchestrator",
        priority="Critical",
    )
    test_store.complete_task(str(archived["id"]), {"ok": True})
    test_store.archive_task(str(archived["id"]))

    with TestClient(main.app) as client:
        response = client.get("/api/tasks")

    assert response.status_code == 200
    tasks = response.json()
    task_ids = [task["id"] for task in tasks]

    assert isinstance(tasks, list)
    assert task_ids[0] == critical["id"]
    assert low["id"] in task_ids
    assert archived["id"] not in task_ids
    assert tasks[0]["priority"] == "Critical"
    assert "archived_at" in tasks[0]


def test_archive_task_api_archives_completed_task(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    task = test_store.create_task(
        title="Completed task to archive",
        description="Completed task should be archivable through the API.",
        agent_name="Orchestrator",
        priority="Medium",
    )
    test_store.complete_task(str(task["id"]), {"ok": True})

    with TestClient(main.app) as client:
        response = client.post(f"/api/tasks/{task['id']}/archive")

    assert response.status_code == 200
    archived = response.json()
    assert archived["id"] == task["id"]
    assert archived["archived_at"] is not None

    visible_ids = {row["id"] for row in test_store.list_tasks()}
    assert task["id"] not in visible_ids


def test_archive_task_api_rejects_active_task(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    task = test_store.create_task(
        title="Active task",
        description="Active task should not be archived.",
        agent_name="Orchestrator",
        priority="Medium",
    )

    with TestClient(main.app) as client:
        response = client.post(f"/api/tasks/{task['id']}/archive")

    assert response.status_code == 409
    assert response.json()["detail"] == "Only completed, failed, blocked, or partial tasks can be archived."


def test_archive_task_api_returns_404_for_missing_task(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    with TestClient(main.app) as client:
        response = client.post("/api/tasks/missing-task/archive")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found."
