from __future__ import annotations

import sqlite3
from pathlib import Path

from store import TaskStore


def make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(
        db_path=tmp_path / "workflow.db",
        audit_log_path=tmp_path / "audit.jsonl",
    )


def test_create_task_persists_workflow_relationship_fields(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    parent = store.create_task(
        title="Parent workflow",
        description="Coordinate a multi-stage workflow.",
        agent_name="Orchestrator",
    )

    child = store.create_task(
        title="Developer stage",
        description="Implement the requested change.",
        agent_name="Developer",
        parent_task_id=str(parent["id"]),
        workflow_id=str(parent["id"]),
        stage_index=1,
    )

    assert child["parent_task_id"] == parent["id"]
    assert child["workflow_id"] == parent["id"]
    assert child["stage_index"] == 1


def test_create_task_defaults_workflow_relationship_fields_to_none(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    task = store.create_task(
        title="Standalone task",
        description="Run independently.",
        agent_name="Orchestrator",
    )

    assert task["parent_task_id"] is None
    assert task["workflow_id"] is None
    assert task["stage_index"] is None


def test_init_schema_migrates_existing_tasks_table_for_workflow_fields(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.db"

    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                side_effect_level TEXT NOT NULL DEFAULT 'none',
                requires_approval INTEGER NOT NULL DEFAULT 0,
                approval_id TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                due_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                error TEXT,
                result_json TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                archived_at TEXT
            )
            """
        )
        db.execute(
            """
            INSERT INTO tasks (
                id, title, description, agent_name, priority, status,
                side_effect_level, requires_approval, source,
                created_at, updated_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-task",
                "Legacy task",
                "Existing task before workflow persistence.",
                "Orchestrator",
                "Medium",
                "queued",
                "none",
                0,
                "manual",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "{}",
            ),
        )

    store = TaskStore(
        db_path=db_path,
        audit_log_path=tmp_path / "legacy-audit.jsonl",
    )

    migrated = store.get_task("legacy-task")

    assert migrated is not None
    assert migrated["title"] == "Legacy task"
    assert migrated["parent_task_id"] is None
    assert migrated["workflow_id"] is None
    assert migrated["stage_index"] is None


def test_create_task_persists_workflow_managed_flag(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    ordinary = store.create_task(
        title="Ordinary task",
        description="Normal queue-managed task.",
        agent_name="Orchestrator",
    )

    parent = store.create_task(
        title="Workflow parent",
        description="Parent orchestration task.",
        agent_name="Orchestrator",
    )

    child = store.create_task(
        title="Managed workflow stage",
        description="Persisted stage executed by the parent orchestrator.",
        agent_name="Developer",
        parent_task_id=str(parent["id"]),
        workflow_id=str(parent["id"]),
        stage_index=1,
        workflow_managed=True,
    )

    assert ordinary["workflow_managed"] == 0
    assert child["workflow_managed"] == 1


def test_claim_next_task_skips_orchestrator_managed_workflow_child(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    parent = store.create_task(
        title="Workflow parent",
        description="Parent orchestration task.",
        agent_name="Orchestrator",
        priority="High",
    )

    child = store.create_task(
        title="Managed workflow stage",
        description="Must not be claimed independently.",
        agent_name="Developer",
        priority="Critical",
        parent_task_id=str(parent["id"]),
        workflow_id=str(parent["id"]),
        stage_index=1,
        workflow_managed=True,
    )

    ordinary = store.create_task(
        title="Ordinary queued task",
        description="This task remains eligible for normal queue claiming.",
        agent_name="QA",
        priority="Medium",
    )

    with store._connect() as db:
        db.execute(
            "UPDATE tasks SET status='running' WHERE id=?",
            (parent["id"],),
        )

    claimed = store.claim_next_task()

    assert claimed is not None
    assert claimed["id"] == ordinary["id"]

    managed_child = store.get_task(str(child["id"]))
    assert managed_child is not None
    assert managed_child["status"] == "queued"


def test_workflow_stage_lifecycle_does_not_change_global_agent_status(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.seed_defaults()

    parent = store.create_task(
        title="Workflow parent",
        description="Coordinate persisted stages.",
        agent_name="Orchestrator",
    )

    child = store.create_task(
        title="Developer stage",
        description="Implement the requested change.",
        agent_name="Developer",
        parent_task_id=str(parent["id"]),
        workflow_id=str(parent["id"]),
        stage_index=1,
        workflow_managed=True,
    )

    with store._connect() as db:
        db.execute(
            "UPDATE agent_status SET status='working', current_task_id=? "
            "WHERE name='Developer'",
            ("other-developer-task",),
        )

    started = store.start_workflow_stage(str(child["id"]))

    assert started["status"] == "running"
    assert started["started_at"] is not None

    finished = store.finish_workflow_stage(
        str(child["id"]),
        status="completed",
        result={
            "summary": "Implementation completed.",
            "evidence": ["verification passed"],
        },
    )

    assert finished["status"] == "completed"
    assert finished["completed_at"] is not None
    assert finished["result_json"] is not None

    with store._connect() as db:
        developer = db.execute(
            "SELECT status, current_task_id FROM agent_status WHERE name='Developer'"
        ).fetchone()

    assert developer is not None
    assert developer["status"] == "working"
    assert developer["current_task_id"] == "other-developer-task"


def test_workflow_stage_transition_rejects_normal_queue_task(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    ordinary = store.create_task(
        title="Ordinary task",
        description="Normal queue-managed task.",
        agent_name="Developer",
    )

    import pytest

    with pytest.raises(PermissionError, match="workflow-managed"):
        store.start_workflow_stage(str(ordinary["id"]))
