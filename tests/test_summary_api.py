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


def test_summary_endpoint_reports_operational_counts(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    completed = test_store.create_task(
        title="Completed summary task",
        description="Completed task should be counted.",
        agent_name="Orchestrator",
        priority="High",
    )
    test_store.complete_task(str(completed["id"]), {"ok": True})

    approval_task = test_store.create_task(
        title="Approval summary task",
        description="Approval task should be waiting.",
        agent_name="Orchestrator",
        priority="Critical",
        side_effect_level="external",
        requires_approval=True,
    )

    archived = test_store.create_task(
        title="Archived summary task",
        description="Archived task should be counted separately.",
        agent_name="Orchestrator",
        priority="Low",
    )
    test_store.complete_task(str(archived["id"]), {"ok": True})
    test_store.archive_task(str(archived["id"]))

    with TestClient(main.app) as client:
        response = client.get("/api/summary")

    assert response.status_code == 200
    summary = response.json()
    assert summary["task_counts"]["completed"] == 1
    assert summary["task_counts"]["awaiting_approval"] == 1
    assert summary["priority_counts"]["High"] == 1
    assert summary["priority_counts"]["Critical"] == 1
    assert summary["approvals_waiting"] == 1
    assert summary["archived_tasks"] == 1
    assert len(summary["agents"]) == 12
    assert any(task["id"] == approval_task["id"] for task in summary["tasks"])
    assert len(summary["approvals"]) == 1
    assert summary["execution_note"].startswith("Agent execution is opt-in")


def test_summary_endpoint_includes_personal_assistant_handoff(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    with TestClient(main.app) as client:
        handoff_response = client.post(
            "/api/assistant/handoff",
            json={
                "request": "Summarize current status for dashboard verification.",
                "priority": "High",
            },
        )
        summary_response = client.get("/api/summary")

    assert handoff_response.status_code == 201
    handoff = handoff_response.json()
    assert handoff["status"] == "queued"
    assert handoff["agent_name"] == "Orchestrator"
    assert handoff["requires_approval"] is False

    summary = summary_response.json()
    task = next(item for item in summary["tasks"] if item["id"] == handoff["task_id"])
    assert task["source"] == "personal-assistant"
    assert task["priority"] == "High"
    assert task["agent_name"] == "Orchestrator"
    assert summary["task_counts"]["queued"] == 1


def test_summary_endpoint_surfaces_attention_tasks_outside_priority_limit(monkeypatch, tmp_path: Path) -> None:
    test_store = make_store(tmp_path)
    monkeypatch.setattr(main, "store", test_store)

    for index in range(25):
        task = test_store.create_task(
            title=f"Medium completed task {index}",
            description="Completed medium task fills the visible priority window.",
            agent_name="Orchestrator",
            priority="Medium",
        )
        test_store.complete_task(str(task["id"]), {"ok": True})

    failed = test_store.create_task(
        title="Low failed task needing attention",
        description="Failed low priority task must remain visible in summary tasks.",
        agent_name="Orchestrator",
        priority="Low",
    )
    test_store.fail_task(str(failed["id"]), "Visible failure")

    with TestClient(main.app) as client:
        response = client.get("/api/summary")

    assert response.status_code == 200
    summary = response.json()
    assert summary["task_counts"]["failed"] == 1
    assert any(task["id"] == failed["id"] for task in summary["tasks"])
