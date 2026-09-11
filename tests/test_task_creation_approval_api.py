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


def test_destructive_task_creation_creates_pending_approval(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/tasks",
            json={
                "title": "Delete obsolete sandbox file",
                "description": r"Delete D:\Shared-Local-Execution-Engine-Sandbox\obsolete.txt after human approval.",
                "priority": "Critical",
            },
        )

    assert response.status_code == 201
    task = response.json()
    assert task["status"] == "awaiting_approval"
    assert task["side_effect_level"] == "destructive"
    assert task["requires_approval"] == 1
    assert task["approval_id"] is not None

    approvals = test_store.list_approvals()
    assert len(approvals) == 1
    assert approvals[0]["id"] == task["approval_id"]
    assert approvals[0]["task_id"] == task["id"]
    assert approvals[0]["status"] == "pending"


def test_approval_api_approves_pending_task(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    with TestClient(main.app) as client:
        created = client.post(
            "/api/tasks",
            json={
                "title": "Send approval gated email",
                "description": "Send email after approval.",
                "priority": "High",
            },
        ).json()

        response = client.post(f"/api/approvals/{created['approval_id']}/approved")

    assert response.status_code == 200
    approval = response.json()
    assert approval["status"] == "approved"

    task = test_store.get_task(created["id"])
    assert task is not None
    assert task["status"] == "queued"
    assert task["error"] is None


def test_approval_api_rejects_pending_task(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    with TestClient(main.app) as client:
        created = client.post(
            "/api/tasks",
            json={
                "title": "Delete obsolete sandbox file",
                "description": r"Delete D:\Shared-Local-Execution-Engine-Sandbox\obsolete.txt after human approval.",
                "priority": "Critical",
            },
        ).json()

        response = client.post(f"/api/approvals/{created['approval_id']}/rejected")

    assert response.status_code == 200
    approval = response.json()
    assert approval["status"] == "rejected"

    task = test_store.get_task(created["id"])
    assert task is not None
    assert task["status"] == "failed"
    assert task["error"] == "Rejected by human reviewer"


def test_approval_api_returns_404_for_missing_approval(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    with TestClient(main.app) as client:
        response = client.post("/api/approvals/missing-approval/approved")

    assert response.status_code == 404
    assert response.json()["detail"] == "approval not found"
