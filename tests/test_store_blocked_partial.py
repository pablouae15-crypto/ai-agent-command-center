from __future__ import annotations

import json
from pathlib import Path

from store import TaskStore


def test_block_task_persists_diagnostics(
    tmp_path: Path,
) -> None:
    store = TaskStore(
        db_path=tmp_path / "blocked.db",
        audit_log_path=tmp_path / "blocked-audit.jsonl",
    )
    store.seed_defaults()

    task = store.create_task(
        title="Blocked task",
        description="Test blocked transition.",
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="none",
        requires_approval=False,
    )

    store.complete_task(
        str(task["id"]),
        {"output": "old result"},
    )

    store.block_task(
        str(task["id"]),
        "Approval is required.",
    )

    current = store.get_task(str(task["id"]))

    assert current is not None
    assert current["status"] == "blocked"
    assert current["error"] == "Approval is required."
    assert current["failure_code"] == "TASK_BLOCKED"
    assert json.loads(current["diagnostics_json"]) == {}
    assert json.loads(current["result_json"]) == {
        "status": "blocked",
        "summary": "Approval is required.",
        "failure_code": "TASK_BLOCKED",
        "diagnostics": {},
    }
    assert current["completed_at"] is None


def test_partial_task_preserves_structured_result(
    tmp_path: Path,
) -> None:
    store = TaskStore(
        db_path=tmp_path / "partial.db",
        audit_log_path=tmp_path / "partial-audit.jsonl",
    )
    store.seed_defaults()

    task = store.create_task(
        title="Partial task",
        description="Test partial transition.",
        agent_name="Orchestrator",
        priority="Medium",
        side_effect_level="none",
        requires_approval=False,
    )

    result = {
        "status": "partial",
        "summary": "Inspection completed; implementation incomplete.",
        "evidence": ["repository inspected"],
    }

    store.partial_task(
        str(task["id"]),
        result,
        "Inspection completed; implementation incomplete.",
    )

    current = store.get_task(str(task["id"]))

    assert current is not None
    assert current["status"] == "partial"
    assert current["error"] == (
        "Inspection completed; implementation incomplete."
    )
    assert current["completed_at"] is None

    persisted = json.loads(current["result_json"])

    assert persisted == result
    assert current["failure_code"] == "TASK_PARTIAL"
    assert json.loads(current["diagnostics_json"]) == {
        "summary": "Inspection completed; implementation incomplete.",
    }
