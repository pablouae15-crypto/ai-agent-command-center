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


def test_external_task_creation_creates_pending_approval(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/tasks",
            json={
                "title": "Send approval gated email",
                "description": "Send email to confirm the approval workflow is protected.",
                "priority": "High",
            },
        )

    assert response.status_code == 201
    task = response.json()
    assert task["status"] == "awaiting_approval"
    assert task["side_effect_level"] == "external"
    assert task["requires_approval"] == 1
    assert task["approval_id"] is not None

    approvals = test_store.list_approvals()
    assert len(approvals) == 1
    assert approvals[0]["id"] == task["approval_id"]
    assert approvals[0]["task_id"] == task["id"]
    assert approvals[0]["status"] == "pending"
