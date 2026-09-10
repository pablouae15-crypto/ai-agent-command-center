from pathlib import Path

from fastapi.testclient import TestClient

import main
from store import TaskStore


def make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(
        tmp_path / "command_center.db",
        tmp_path / "audit.jsonl",
    )


def test_archive_task_endpoint_hides_blocked_task(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    task = test_store.create_task(
        title="Blocked cleanup task",
        description="Blocked cleanup task.",
        agent_name="Orchestrator",
        priority="Medium",
    )

    with test_store._connect() as db:
        db.execute(
            "UPDATE tasks SET status='blocked' WHERE id=?",
            (task["id"],),
        )

    with TestClient(main.app) as client:
        response = client.post(f"/api/tasks/{task['id']}/archive")

    assert response.status_code == 200
    body = response.json()
    assert body["archived_at"] is not None
    assert task["id"] not in {row["id"] for row in test_store.list_tasks()}
    assert task["id"] in {
        row["id"] for row in test_store.list_tasks(include_archived=True)
    }


def test_archive_task_endpoint_rejects_active_task(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    task = test_store.create_task(
        title="Active task",
        description="Active task.",
        agent_name="Orchestrator",
        priority="Medium",
    )

    with TestClient(main.app) as client:
        response = client.post(f"/api/tasks/{task['id']}/archive")

    assert response.status_code == 409


def test_archive_task_endpoint_returns_404_for_missing_task(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    with TestClient(main.app) as client:
        response = client.post("/api/tasks/missing-task/archive")

    assert response.status_code == 404
