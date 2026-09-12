from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from write_approval import (
    VerifiedApprovalRequest,
    VerifiedEditBatchRequest,
    VerifiedGmailDraftRequest,
    approval_action_for_request,
)


PRIORITIES = ("Critical", "High", "Medium", "Low")
STATUSES = ("queued", "running", "awaiting_approval", "completed", "failed", "blocked", "partial")


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    def __init__(self, db_path: Path, audit_log_path: Path):
        self.db_path = Path(db_path)
        self.audit_log_path = Path(audit_log_path)
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def init_schema(self) -> None:
        with self._lock, self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
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
                    archived_at TEXT,
                    parent_task_id TEXT,
                    workflow_id TEXT,
                    stage_index INTEGER,
                    workflow_managed INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(status, priority, created_at);
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    display_payload_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    task_id TEXT,
                    agent_name TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_status (
                    name TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    description TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    current_task_id TEXT
                );
                CREATE TABLE IF NOT EXISTS recurring_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    agent_name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    next_run_at TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gmail_draft_executions (
                    approval_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    gmail_draft_id TEXT,
                    gmail_message_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(approval_id) REFERENCES approvals(id),
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                """
            )

            task_columns = {
                row["name"]
                for row in db.execute(
                    "PRAGMA table_info(tasks)"
                ).fetchall()
            }

            if "archived_at" not in task_columns:
                db.execute(
                    "ALTER TABLE tasks "
                    "ADD COLUMN archived_at TEXT"
                )

            if "parent_task_id" not in task_columns:
                db.execute(
                    "ALTER TABLE tasks "
                    "ADD COLUMN parent_task_id TEXT"
                )

            if "workflow_id" not in task_columns:
                db.execute(
                    "ALTER TABLE tasks "
                    "ADD COLUMN workflow_id TEXT"
                )

            if "stage_index" not in task_columns:
                db.execute(
                    "ALTER TABLE tasks "
                    "ADD COLUMN stage_index INTEGER"
                )

            if "workflow_managed" not in task_columns:
                db.execute(
                    "ALTER TABLE tasks "
                    "ADD COLUMN workflow_managed INTEGER NOT NULL DEFAULT 0"
                )

            approval_columns = {
                row["name"]
                for row in db.execute(
                    "PRAGMA table_info(approvals)"
                ).fetchall()
            }

            if "display_payload_json" not in approval_columns:
                db.execute(
                    "ALTER TABLE approvals "
                    "ADD COLUMN display_payload_json "
                    "TEXT NOT NULL DEFAULT '{}'"
                )

    def seed_defaults(self) -> None:
        now = utc_now()
        agents = [
            ("Orchestrator", "idle", "Coordinates safe local tasks and proposes next actions."),
            ("Developer", "idle", "Implements, debugs, and refactors code through approved local tools only."),
            ("QA", "idle", "Designs and runs tests, verifies regressions, and analyzes defects."),
            ("UIUX", "idle", "Reviews and improves interface structure, usability, and implementation."),
            ("CodeReviewer", "idle", "Reviews code quality, maintainability, correctness, and security."),
            ("SecurityReviewer", "idle", "Reviews security controls, authorization boundaries, exposure risks, and secure implementation."),
            ("Documentation", "idle", "Produces evidence-based technical documentation, architecture notes, and operating guidance."),
            ("Executive Assistant", "idle", "Plans, summarizes, organizes, and coordinates approved work inside the Command Center."),
            ("Email / Calendar", "idle", "Provides read-only Gmail search/read and Google Calendar event listing."),
            ("HR & Compliance", "idle", "Provides controlled HR policy, process, workforce, and compliance analysis."),
            ("Job Tracker", "idle", "Tracks job opportunities, applications, follow-ups, and duplicate-submission risk."),
            ("Research / News", "idle", "Performs read-only public web research using the hosted web-search connector."),
        ]
        with self._lock, self._connect() as db:
            for name, status, description in agents:
                db.execute(
                    """INSERT INTO agent_status(name,status,description,last_seen_at)
                       VALUES(?,?,?,?)
                       ON CONFLICT(name) DO UPDATE SET
                           status=CASE
                               WHEN agent_status.status='placeholder'
                               THEN excluded.status
                               ELSE agent_status.status
                           END,
                           description=excluded.description""",
                    (name, status, description, now),
                )
        with self._connect() as db:
            existing_initialization = db.execute(
                "SELECT 1 FROM activity "
                "WHERE event_type=? AND message=? "
                "LIMIT 1",
                ("system", "Command Center initialized"),
            ).fetchone()

        if not existing_initialization:
            self.add_activity("system", "Command Center initialized", payload={"seeded_agents": len(agents)})

    def _row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def create_task(
        self,
        title: str,
        description: str,
        agent_name: str = "Orchestrator",
        priority: str = "Medium",
        side_effect_level: str = "none",
        requires_approval: bool = False,
        source: str = "manual",
        due_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        defer_exact_approval: bool = False,
        parent_task_id: str | None = None,
        workflow_id: str | None = None,
        stage_index: int | None = None,
        workflow_managed: bool = False,
    ) -> dict[str, Any]:
        if priority not in PRIORITIES:
            raise ValueError(f"priority must be one of {PRIORITIES}")
        if side_effect_level not in {"none", "external", "destructive"}:
            raise ValueError("side_effect_level must be none, external, or destructive")
        requires_approval = bool(requires_approval or side_effect_level != "none")
        metadata_payload = dict(metadata or {})
        if defer_exact_approval:
            metadata_payload["_defer_exact_approval"] = True
        initial_status = (
            "awaiting_approval"
            if requires_approval and not defer_exact_approval
            else "queued"
        )
        task_id = str(uuid.uuid4())
        now = utc_now()
        with self._lock, self._connect() as db:
            db.execute(
                """INSERT INTO tasks
                   (id,title,description,agent_name,priority,status,side_effect_level,
                    requires_approval,source,created_at,updated_at,due_at,metadata_json,
                    parent_task_id,workflow_id,stage_index,workflow_managed)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id, title, description, agent_name, priority,
                    initial_status, side_effect_level, int(requires_approval), source,
                    now, now, due_at, json.dumps(metadata_payload),
                    parent_task_id, workflow_id, stage_index,
                    int(workflow_managed),
                ),
            )
        self.add_activity("task.created", f"Task created: {title}", task_id=task_id, agent_name=agent_name,
                          payload={"priority": priority, "requires_approval": requires_approval, "source": source})
        if requires_approval and not defer_exact_approval:
            self.ensure_approval(task_id)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            return self._row(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def list_workflow_tasks(self, workflow_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM tasks
                   WHERE workflow_id=? AND workflow_managed=1
                   ORDER BY stage_index ASC, created_at ASC""",
                (workflow_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_tasks(self, limit: int = 100, include_archived: bool = False) -> list[dict[str, Any]]:
        with self._connect() as db:
            where_clause = (
                "WHERE workflow_managed=0"
                if include_archived
                else "WHERE archived_at IS NULL AND workflow_managed=0"
            )
            rows = db.execute(
                f"SELECT * FROM tasks {where_clause} "
                "ORDER BY CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        with self._connect() as db:
            counts = {
                row["status"]: row["count"]
                for row in db.execute(
                    "SELECT status, COUNT(*) AS count FROM tasks "
                    "WHERE archived_at IS NULL AND workflow_managed=0 GROUP BY status"
                )
            }
            priority_counts = {
                row["priority"]: row["count"]
                for row in db.execute(
                    "SELECT priority, COUNT(*) AS count FROM tasks "
                    "WHERE archived_at IS NULL AND workflow_managed=0 GROUP BY priority"
                )
            }
            archived_count = db.execute(
                "SELECT COUNT(*) AS count FROM tasks "
                "WHERE archived_at IS NOT NULL AND workflow_managed=0"
            ).fetchone()["count"]
            pending = db.execute(
                "SELECT COUNT(*) AS count FROM approvals WHERE status='pending'"
            ).fetchone()["count"]
            return {
                "task_counts": counts,
                "priority_counts": priority_counts,
                "approvals_waiting": pending,
                "archived_tasks": archived_count,
            }

    def archive_task(self, task_id: str) -> dict[str, Any] | None:
        now = utc_now()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()

            if not row:
                return None

            if row["status"] in {"queued", "running", "awaiting_approval"}:
                raise PermissionError(
                    "Only completed, failed, blocked, or partial tasks can be archived."
                )

            db.execute(
                "UPDATE tasks SET archived_at=?, updated_at=? WHERE id=?",
                (now, now, task_id),
            )

        self.add_activity(
            "task.archived",
            f"Task archived: {task_id}",
            task_id=task_id,
            payload={"archived_at": now},
        )

        return self.get_task(task_id)


    def claim_next_task(self) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                """SELECT * FROM tasks
                   WHERE status='queued'
                     AND workflow_managed=0
                     AND (
                         requires_approval=0
                         OR (
                             approval_id IS NULL
                             AND json_extract(metadata_json, '$._defer_exact_approval') = 1
                         )
                         OR EXISTS (
                             SELECT 1
                             FROM approvals
                             WHERE approvals.id=tasks.approval_id
                               AND approvals.task_id=tasks.id
                               AND approvals.status='approved'
                         )
                     )
                   ORDER BY CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
                   created_at LIMIT 1"""
            ).fetchone()
            if not row:
                return None
            now = utc_now()
            db.execute("UPDATE tasks SET status='running', started_at=?, updated_at=? WHERE id=?", (now, now, row["id"]))
            db.execute("UPDATE agent_status SET status='working', current_task_id=?, last_seen_at=? WHERE name=?", (row["id"], now, row["agent_name"]))
        task = self.get_task(row["id"])
        self.add_activity("task.started", f"Task started: {task['title']}", task_id=task["id"], agent_name=task["agent_name"])
        return task

    def recover_interrupted_tasks(self) -> list[dict[str, Any]]:
        """Recover tasks left running when the server stopped unexpectedly."""
        now = utc_now()
        recovered: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        side_effect_reason = (
            "Execution was interrupted by a server restart. Manual review is "
            "required before retrying because the task may have side effects."
        )

        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM tasks WHERE status='running'"
            ).fetchall()

            for row in rows:
                task = dict(row)
                if task["side_effect_level"] == "none":
                    db.execute(
                        "UPDATE tasks SET status='queued', started_at=NULL, "
                        "completed_at=NULL, updated_at=?, error=NULL WHERE id=?",
                        (now, task["id"]),
                    )
                    recovered.append(task)
                else:
                    db.execute(
                        "UPDATE tasks SET status='blocked', started_at=NULL, "
                        "completed_at=NULL, updated_at=?, error=?, "
                        "result_json=NULL WHERE id=?",
                        (now, side_effect_reason, task["id"]),
                    )
                    blocked.append(task)

                db.execute(
                    "UPDATE agent_status SET status='idle', current_task_id=NULL, "
                    "last_seen_at=? WHERE current_task_id=?",
                    (now, task["id"]),
                )

        for task in recovered:
            self.add_activity(
                "task.requeued",
                f"Task requeued after server restart: {task['title']}",
                task_id=task["id"],
                agent_name=task["agent_name"],
                payload={"reason": "server_restart"},
            )

        for task in blocked:
            self.add_activity(
                "task.blocked",
                f"Task blocked after server restart: {task['title']}",
                task_id=task["id"],
                agent_name=task["agent_name"],
                payload={"reason": side_effect_reason},
            )

        return recovered + blocked

    def start_workflow_stage(self, task_id: str) -> dict[str, Any]:
        now = utc_now()

        with self._lock, self._connect() as db:
            task = db.execute(
                "SELECT * FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()

            if not task:
                raise ValueError("task not found")

            if not task["workflow_managed"]:
                raise PermissionError(
                    "Workflow stage transitions require a workflow-managed task."
                )

            if task["status"] != "queued":
                raise ValueError(
                    "Workflow stage must be queued before it can start."
                )

            db.execute(
                "UPDATE tasks SET status='running', started_at=?, "
                "updated_at=?, completed_at=NULL, error=NULL WHERE id=?",
                (now, now, task_id),
            )

        self.add_activity(
            "workflow.stage_started",
            f"Workflow stage started: {task['title']}",
            task_id=task_id,
            agent_name=task["agent_name"],
            payload={
                "workflow_id": task["workflow_id"],
                "parent_task_id": task["parent_task_id"],
                "stage_index": task["stage_index"],
            },
        )

        updated = self.get_task(task_id)
        if updated is None:
            raise RuntimeError("Workflow stage disappeared after start.")
        return updated

    def resume_workflow_stage(self, task_id: str) -> dict[str, Any]:
        now = utc_now()

        with self._lock, self._connect() as db:
            task = db.execute(
                "SELECT * FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()

            if not task:
                raise ValueError("task not found")

            if not task["workflow_managed"]:
                raise PermissionError(
                    "Workflow stage transitions require a workflow-managed task."
                )

            if task["status"] != "blocked":
                raise ValueError(
                    "Only a blocked workflow stage can be resumed."
                )

            db.execute(
                "UPDATE tasks SET status='running', updated_at=?, "
                "completed_at=NULL, error=NULL WHERE id=?",
                (now, task_id),
            )

        self.add_activity(
            "workflow.stage_resumed",
            f"Workflow stage resumed: {task['title']}",
            task_id=task_id,
            agent_name=task["agent_name"],
            payload={
                "workflow_id": task["workflow_id"],
                "parent_task_id": task["parent_task_id"],
                "stage_index": task["stage_index"],
            },
        )

        updated = self.get_task(task_id)
        if updated is None:
            raise RuntimeError("Workflow stage disappeared after resume.")
        return updated

    def finish_workflow_stage(
        self,
        task_id: str,
        status: str,
        result: Any,
    ) -> dict[str, Any]:
        if status not in {"completed", "failed", "blocked", "partial"}:
            raise ValueError(
                "Workflow stage status must be completed, failed, blocked, or partial."
            )

        now = utc_now()

        with self._lock, self._connect() as db:
            task = db.execute(
                "SELECT * FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()

            if not task:
                raise ValueError("task not found")

            if not task["workflow_managed"]:
                raise PermissionError(
                    "Workflow stage transitions require a workflow-managed task."
                )

            if task["status"] != "running":
                raise ValueError(
                    "Workflow stage must be running before it can finish."
                )

            summary = ""
            if isinstance(result, dict):
                summary = str(result.get("summary") or "")

            completed_at = now if status == "completed" else None
            error = summary[:2000] if status in {"failed", "blocked", "partial"} else None

            db.execute(
                "UPDATE tasks SET status=?, completed_at=?, updated_at=?, "
                "result_json=?, error=? WHERE id=?",
                (
                    status,
                    completed_at,
                    now,
                    json.dumps(result),
                    error,
                    task_id,
                ),
            )

        self.add_activity(
            "workflow.stage_finished",
            f"Workflow stage finished with status {status}: {task['title']}",
            task_id=task_id,
            agent_name=task["agent_name"],
            payload={
                "workflow_id": task["workflow_id"],
                "parent_task_id": task["parent_task_id"],
                "stage_index": task["stage_index"],
                "status": status,
            },
        )

        updated = self.get_task(task_id)
        if updated is None:
            raise RuntimeError("Workflow stage disappeared after finish.")
        return updated

    def requeue_running_task(self, task_id: str, reason: str) -> dict[str, Any]:
        now = utc_now()
        task = self.get_task(task_id)

        if task is None:
            raise ValueError("task not found")

        if task["workflow_managed"]:
            raise PermissionError(
                "Workflow-managed tasks must use workflow stage transitions."
            )

        if task["status"] != "running":
            raise ValueError("Only a running task can be requeued.")

        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE tasks SET status='queued', updated_at=?, completed_at=NULL, "
                "error=NULL, approval_id=NULL WHERE id=?",
                (now, task_id),
            )
            db.execute(
                "UPDATE agent_status SET status='idle', current_task_id=NULL, "
                "last_seen_at=? WHERE name=?",
                (now, task["agent_name"]),
            )

        self.add_activity(
            "task.requeued",
            f"Task requeued: {task['title']}",
            task_id=task_id,
            agent_name=task["agent_name"],
            payload={"reason": reason[:500]},
        )

        updated = self.get_task(task_id)
        if updated is None:
            raise RuntimeError("Task disappeared after requeue.")
        return updated


    def complete_task(self, task_id: str, result: Any) -> None:
        now = utc_now()
        task = self.get_task(task_id)
        with self._lock, self._connect() as db:
            db.execute("UPDATE tasks SET status='completed', completed_at=?, updated_at=?, result_json=?, error=NULL WHERE id=?", (now, now, json.dumps(result), task_id))
            if task:
                db.execute("UPDATE agent_status SET status='idle', current_task_id=NULL, last_seen_at=? WHERE name=?", (now, task["agent_name"]))
        self.add_activity("task.completed", f"Task completed: {task['title'] if task else task_id}", task_id=task_id,
                          agent_name=task["agent_name"] if task else None)

    def fail_task(self, task_id: str, error: str) -> None:
        now = utc_now()
        task = self.get_task(task_id)
        with self._lock, self._connect() as db:
            db.execute("UPDATE tasks SET status='failed', error=?, updated_at=?, result_json=NULL, completed_at=NULL WHERE id=?", (error[:2000], now, task_id))
            if task:
                db.execute("UPDATE agent_status SET status='idle', current_task_id=NULL, last_seen_at=? WHERE name=?", (now, task["agent_name"]))
        self.add_activity("task.failed", f"Task failed: {task['title'] if task else task_id}", task_id=task_id,
                          agent_name=task["agent_name"] if task else None, payload={"error": error[:500]})

    def block_task(self, task_id: str, reason: str) -> None:
        now = utc_now()
        task = self.get_task(task_id)
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE tasks SET status='blocked', error=?, updated_at=?, "
                "result_json=NULL, completed_at=NULL WHERE id=?",
                (reason[:2000], now, task_id),
            )
            if task:
                db.execute(
                    "UPDATE agent_status SET status='idle', "
                    "current_task_id=NULL, last_seen_at=? WHERE name=?",
                    (now, task["agent_name"]),
                )
        self.add_activity(
            "task.blocked",
            f"Task blocked: {task['title'] if task else task_id}",
            task_id=task_id,
            agent_name=task["agent_name"] if task else None,
            payload={"reason": reason[:500]},
        )

    def partial_task(
        self,
        task_id: str,
        result: Any,
        summary: str,
    ) -> None:
        now = utc_now()
        task = self.get_task(task_id)
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE tasks SET status='partial', error=?, updated_at=?, "
                "result_json=?, completed_at=NULL WHERE id=?",
                (
                    summary[:2000],
                    now,
                    json.dumps(result),
                    task_id,
                ),
            )
            if task:
                db.execute(
                    "UPDATE agent_status SET status='idle', "
                    "current_task_id=NULL, last_seen_at=? WHERE name=?",
                    (now, task["agent_name"]),
                )
        self.add_activity(
            "task.partial",
            f"Task partial: {task['title'] if task else task_id}",
            task_id=task_id,
            agent_name=task["agent_name"] if task else None,
            payload={"summary": summary[:500]},
        )

    def create_exact_approval(
        self,
        request: VerifiedApprovalRequest,
        reason: str = "Verified request approval",
    ) -> dict[str, Any]:
        task = self.get_task(request.task_id)
        if not task:
            raise ValueError("task not found")

        action = approval_action_for_request(request)

        display_payload: dict[str, Any] = {}

        if isinstance(request, VerifiedGmailDraftRequest):
            display_payload = {
                "type": "gmail_draft",
                "to": list(request.to),
                "cc": list(request.cc),
                "bcc": list(request.bcc),
                "subject": request.subject,
                "body": request.body,
            }

        elif isinstance(request, VerifiedEditBatchRequest):
            display_payload = {
            "type": "verified_edit_batch_execution",
            "capability": request.capability,
            "repository_path": request.repository_path,
            "verification_profile": request.verification_profile,
            "edits": [
            {
            "path": edit.path,
            "old_text": edit.old_text,
            "new_text": edit.new_text,
            "expected_replacements": edit.expected_replacements,
            }
            for edit in request.edits
            ],
            }

        elif request.capability == "replace_text":
            display_payload = {
                "type": "verified_edit_execution",
                "capability": request.capability,
                "path": request.path,
                "repository_path": request.repository_path,
                "verification_profile": request.verification_profile,
                "old_text": request.old_text,
                "new_text": request.new_text,
                "expected_replacements": request.expected_replacements,
            }

        elif request.capability == "write_text_file":
            display_payload = {
                "type": "verified_file_write_execution",
                "capability": request.capability,
                "path": request.path,
                "repository_path": request.repository_path,
                "verification_profile": request.verification_profile,
                "content": request.content,
                "expected_sha256": request.expected_sha256,
            }

        display_payload_json = json.dumps(
            display_payload,
            sort_keys=True,
            separators=(",", ":"),
        )

        with self._lock, self._connect() as db:
            existing = db.execute(
                "SELECT * FROM approvals "
                "WHERE task_id=? "
                "AND action=? "
                "AND status='pending' "
                "AND display_payload_json=?",
                (request.task_id, action, display_payload_json),
            ).fetchone()

            if existing:
                approval = dict(existing)
            else:
                now = utc_now()

                # An exact verified approval supersedes the generic approval
                # that create_task() may have created for the same task.
                db.execute(
                    """
                    UPDATE approvals
                    SET status='superseded',
                        decided_at=?,
                        decided_by='system:exact-approval'
                    WHERE task_id=?
                      AND action=?
                      AND status IN ('pending', 'approved')
                    """,
                    (
                        now,
                        request.task_id,
                        task["title"],
                    ),
                )

                approval_id = str(uuid.uuid4())
                db.execute(
                    "INSERT INTO approvals("
                    "id,task_id,action,reason,created_at,display_payload_json"
                    ") VALUES(?,?,?,?,?,?)",
                    (
                        approval_id,
                        request.task_id,
                        action,
                        reason,
                        now,
                        display_payload_json,
                    ),
                )
                db.execute(
                    "UPDATE tasks SET status='awaiting_approval', "
                    "approval_id=?, updated_at=? WHERE id=?",
                    (approval_id, now, request.task_id),
                )
                approval = dict(
                    db.execute(
                        "SELECT * FROM approvals WHERE id=?",
                        (approval_id,),
                    ).fetchone()
                )

        self.add_activity(
            "approval.requested",
            "Exact verified approval requested",
            task_id=request.task_id,
            agent_name=task["agent_name"],
            payload={
                "approval_id": approval["id"],
                "capability": request.capability,
            },
        )
        return approval

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM approvals WHERE id=?",
                (approval_id,),
            ).fetchone()
            return dict(row) if row else None

    def begin_gmail_draft_execution(
        self,
        approval_id: str,
        task_id: str,
    ) -> dict[str, Any]:
        now = utc_now()

        with self._lock, self._connect() as db:
            existing = db.execute(
                "SELECT * FROM gmail_draft_executions "
                "WHERE approval_id=?",
                (approval_id,),
            ).fetchone()

            if existing:
                return dict(existing)

            db.execute(
                "INSERT INTO gmail_draft_executions("
                "approval_id,task_id,status,created_at,updated_at"
                ") VALUES(?,?,?,?,?)",
                (
                    approval_id,
                    task_id,
                    "creating",
                    now,
                    now,
                ),
            )

            created = db.execute(
                "SELECT * FROM gmail_draft_executions "
                "WHERE approval_id=?",
                (approval_id,),
            ).fetchone()

        return dict(created)


    def complete_gmail_draft_execution(
        self,
        approval_id: str,
        gmail_draft_id: str | None,
        gmail_message_id: str | None,
    ) -> dict[str, Any]:
        now = utc_now()

        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM gmail_draft_executions "
                "WHERE approval_id=?",
                (approval_id,),
            ).fetchone()

            if not row:
                raise ValueError(
                    "Gmail draft execution was not started."
                )

            if row["status"] == "created":
                return dict(row)

            if row["status"] != "creating":
                raise PermissionError(
                    "Gmail draft execution is not in creating state."
                )

            db.execute(
                "UPDATE gmail_draft_executions "
                "SET status='created', "
                "gmail_draft_id=?, gmail_message_id=?, "
                "error=NULL, updated_at=? "
                "WHERE approval_id=?",
                (
                    gmail_draft_id,
                    gmail_message_id,
                    now,
                    approval_id,
                ),
            )

            completed = db.execute(
                "SELECT * FROM gmail_draft_executions "
                "WHERE approval_id=?",
                (approval_id,),
            ).fetchone()

        return dict(completed)


    def fail_gmail_draft_execution(
        self,
        approval_id: str,
        error: str,
    ) -> dict[str, Any]:
        now = utc_now()

        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM gmail_draft_executions "
                "WHERE approval_id=?",
                (approval_id,),
            ).fetchone()

            if not row:
                raise ValueError(
                    "Gmail draft execution was not started."
                )

            if row["status"] == "created":
                return dict(row)

            db.execute(
                "UPDATE gmail_draft_executions "
                "SET status='failed', error=?, updated_at=? "
                "WHERE approval_id=?",
                (
                    error[:2000],
                    now,
                    approval_id,
                ),
            )

            failed = db.execute(
                "SELECT * FROM gmail_draft_executions "
                "WHERE approval_id=?",
                (approval_id,),
            ).fetchone()

        return dict(failed)


    def get_gmail_draft_execution(
        self,
        approval_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM gmail_draft_executions "
                "WHERE approval_id=?",
                (approval_id,),
            ).fetchone()

        return dict(row) if row else None


    def ensure_approval(self, task_id: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            raise ValueError("task not found")
        with self._lock, self._connect() as db:
            existing = db.execute(
                "SELECT * FROM approvals "
                "WHERE task_id=? AND action=? AND status='pending'",
                (task_id, task["title"]),
            ).fetchone()
            if existing:
                approval = dict(existing)
            else:
                approval_id = str(uuid.uuid4())
                reason = "This task requests an external or destructive side effect."
                db.execute("INSERT INTO approvals(id,task_id,action,reason,created_at) VALUES(?,?,?,?,?)",
                           (approval_id, task_id, task["title"], reason, utc_now()))
                db.execute("UPDATE tasks SET status='awaiting_approval', approval_id=?, updated_at=? WHERE id=?",
                           (approval_id, utc_now(), task_id))
                approval = dict(db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone())
        self.add_activity("approval.requested", f"Approval requested: {task['title']}", task_id=task_id,
                          agent_name=task["agent_name"], payload={"approval_id": approval["id"]})
        return approval

    def list_approvals(self, status: str = "pending") -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM approvals WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
            return [dict(row) for row in rows]

    def decide_approval(
        self,
        approval_id: str,
        decision: str,
        decided_by: str = "local-user",
    ) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")

        now = utc_now()
        terminal_statuses = {"completed", "failed", "partial"}

        with self._lock, self._connect() as db:
            approval = db.execute(
                "SELECT * FROM approvals WHERE id=?",
                (approval_id,),
            ).fetchone()

            if not approval:
                raise ValueError("approval not found")

            if approval["status"] != "pending":
                return dict(approval)

            task = db.execute(
                "SELECT * FROM tasks WHERE id=?",
                (approval["task_id"],),
            ).fetchone()

            if not task:
                raise ValueError("approval task not found")

            try:
                approval_action = json.loads(str(approval["action"]))
            except (TypeError, ValueError):
                approval_action = {}

            blocked_exact_approval = (
                task["status"] == "blocked"
                and task["approval_id"] == approval_id
                and approval_action.get("type")
                in {"verified_edit", "verified_file_write"}
            )

            if (
                task["status"] in terminal_statuses
                or (
                    task["status"] == "blocked"
                    and not blocked_exact_approval
                )
            ):
                db.execute(
                    """
                    UPDATE approvals
                    SET status='superseded',
                        decided_at=?,
                        decided_by='system:terminal-task'
                    WHERE id=?
                      AND status='pending'
                    """,
                    (now, approval_id),
                )
                result = dict(
                    db.execute(
                        "SELECT * FROM approvals WHERE id=?",
                        (approval_id,),
                    ).fetchone()
                )
            else:
                db.execute(
                    """
                    UPDATE approvals
                    SET status=?,
                        decided_at=?,
                        decided_by=?
                    WHERE id=?
                    """,
                    (decision, now, decided_by, approval_id),
                )

                task_status = "queued" if decision == "approved" else "failed"
                error = None if decision == "approved" else "Rejected by human reviewer"

                db.execute(
                    """
                    UPDATE tasks
                    SET status=?,
                        error=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        task_status,
                        error,
                        now,
                        approval["task_id"],
                    ),
                )

                result = dict(
                    db.execute(
                        "SELECT * FROM approvals WHERE id=?",
                        (approval_id,),
                    ).fetchone()
                )

        if result["status"] == "superseded":
            self.add_activity(
                "approval.superseded",
                f"Approval superseded because task is already terminal: {approval['action']}",
                task_id=approval["task_id"],
                payload={
                    "approval_id": approval_id,
                    "decided_by": "system:terminal-task",
                },
            )
        else:
            self.add_activity(
                f"approval.{decision}",
                f"Approval {decision}: {approval['action']}",
                task_id=approval["task_id"],
                payload={
                    "approval_id": approval_id,
                    "decided_by": decided_by,
                },
            )

        return result

    def list_agents(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM agent_status ORDER BY name")]

    def list_activity(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))]

    def list_task_visibility(self, limit: int = 25) -> list[dict[str, Any]]:
        attention_statuses = {"failed", "running", "queued", "awaiting_approval"}
        tasks = self.list_tasks(limit)
        missing_attention = [
            task
            for task in self.list_tasks(500)
            if task["status"] in attention_statuses
            and all(existing["id"] != task["id"] for existing in tasks)
        ]
        tasks = (missing_attention + tasks)[:limit]

        with self._connect() as db:
            for task in tasks:
                route = db.execute(
                    """SELECT payload_json, created_at
                       FROM activity
                       WHERE task_id=? AND event_type='orchestrator.routed'
                       ORDER BY id DESC LIMIT 1""",
                    (task["id"],),
                ).fetchone()

                latest = db.execute(
                    """SELECT event_type, created_at
                       FROM activity
                       WHERE task_id=?
                       ORDER BY id DESC LIMIT 1""",
                    (task["id"],),
                ).fetchone()

                task["routed_specialist"] = None
                task["routing_reason"] = None

                if route:
                    try:
                        payload = json.loads(route["payload_json"] or "{}")
                    except json.JSONDecodeError:
                        payload = {}

                    task["routed_specialist"] = payload.get("selected_specialist")
                    task["routing_reason"] = payload.get("reason")

                task["latest_activity_type"] = latest["event_type"] if latest else None
                task["latest_activity_at"] = latest["created_at"] if latest else None

        return tasks

    def add_activity(self, event_type: str, message: str, task_id: str | None = None,
                     agent_name: str | None = None, payload: dict[str, Any] | None = None) -> None:
        now = utc_now()
        payload = payload or {}
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO activity(event_type,message,task_id,agent_name,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                       (event_type, message, task_id, agent_name, json.dumps(payload), now))
        record = {"timestamp": now, "event_type": event_type, "message": message, "task_id": task_id,
                  "agent_name": agent_name, "payload": payload}
        with self.audit_log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")

    def create_job(
        self,
        name: str,
        agent_name: str,
        prompt: str,
        interval_seconds: int,
        next_run_at: str,
        enabled: bool = True,
    ) -> dict[str, Any]:
        name = name.strip()
        agent_name = agent_name.strip()
        prompt = prompt.strip()

        if not name:
            raise ValueError("Recurring job name is required.")
        if not agent_name:
            raise ValueError("Recurring job agent_name is required.")
        if not prompt:
            raise ValueError("Recurring job prompt is required.")
        if interval_seconds < 3600:
            raise ValueError(
                "Recurring job interval_seconds must be at least 3600."
            )
        if not next_run_at.strip():
            raise ValueError("Recurring job next_run_at is required.")

        job_id = str(uuid.uuid4())
        created_at = utc_now()

        with self._lock, self._connect() as db:
            agent = db.execute(
                "SELECT status FROM agent_status WHERE name=?",
                (agent_name,),
            ).fetchone()

            if agent is None:
                raise ValueError(
                    f"Recurring job agent is not registered: {agent_name}"
                )

            if agent["status"] == "placeholder":
                raise ValueError(
                    f"Recurring job agent is not executable: {agent_name}"
                )

            db.execute(
                """INSERT INTO recurring_jobs(
                    id,
                    name,
                    agent_name,
                    prompt,
                    interval_seconds,
                    next_run_at,
                    enabled,
                    created_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    job_id,
                    name,
                    agent_name,
                    prompt,
                    interval_seconds,
                    next_run_at,
                    1 if enabled else 0,
                    created_at,
                ),
            )

        return {
            "id": job_id,
            "name": name,
            "agent_name": agent_name,
            "prompt": prompt,
            "interval_seconds": interval_seconds,
            "next_run_at": next_run_at,
            "enabled": 1 if enabled else 0,
            "created_at": created_at,
        }

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM recurring_jobs ORDER BY created_at, name"
                )
            ]

    def due_jobs(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM recurring_jobs WHERE enabled=1 AND next_run_at<=?", (utc_now(),))]

    def advance_job(self, job_id: str, interval_seconds: int) -> None:
        from datetime import timedelta

        next_run = (datetime.now(timezone.utc) + timedelta(seconds=interval_seconds)).isoformat()
        with self._lock, self._connect() as db:
            db.execute("UPDATE recurring_jobs SET next_run_at=? WHERE id=?", (next_run, job_id))
