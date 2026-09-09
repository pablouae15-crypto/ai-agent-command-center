from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from write_approval import VerifiedApprovalRequest, approval_action_for_request


PRIORITIES = ("Critical", "High", "Medium", "Low")
STATUSES = ("queued", "running", "awaiting_approval", "completed", "failed")


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
                    metadata_json TEXT NOT NULL DEFAULT '{}'
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
                """
            )

    def seed_defaults(self) -> None:
        now = utc_now()
        agents = [
            ("Orchestrator", "idle", "Coordinates safe local tasks and proposes next actions."),
            ("Developer", "idle", "Implements, debugs, and refactors code through approved local tools only."),
            ("QA", "idle", "Designs and runs tests, verifies regressions, and analyzes defects."),
            ("UIUX", "idle", "Reviews and improves interface structure, usability, and implementation."),
            ("CodeReviewer", "idle", "Reviews code quality, maintainability, correctness, and security."),
            ("Executive Assistant", "idle", "Plans, summarizes, organizes, and coordinates approved work inside the Command Center."),
            ("Email / Calendar", "idle", "Provides read-only Gmail search/read and Google Calendar event listing."),
            ("HR & Compliance", "placeholder", "Placeholder; local policy review only."),
            ("Job Tracker", "placeholder", "Placeholder; local tracking only."),
            ("Research / News", "idle", "Performs read-only public web research using the hosted web-search connector."),
            ("Command Center Updater", "placeholder", "Placeholder; updates local state only."),
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
            db.execute(
                """UPDATE recurring_jobs
                   SET enabled=0
                   WHERE name='command-center-heartbeat'
                     AND agent_name='Command Center Updater'"""
            )

            existing = db.execute("SELECT COUNT(*) AS count FROM recurring_jobs").fetchone()["count"]
            if existing == 0:
                db.execute(
                    """INSERT INTO recurring_jobs
                       (id,name,agent_name,prompt,interval_seconds,next_run_at,enabled,created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        str(uuid.uuid4()),
                        "command-center-heartbeat",
                        "Command Center Updater",
                        "Review local task and approval counts and report any stale work.",
                        300,
                        now,
                        0,
                        now,
                    ),
                )
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
    ) -> dict[str, Any]:
        if priority not in PRIORITIES:
            raise ValueError(f"priority must be one of {PRIORITIES}")
        if side_effect_level not in {"none", "external", "destructive"}:
            raise ValueError("side_effect_level must be none, external, or destructive")
        requires_approval = bool(requires_approval or side_effect_level != "none")
        task_id = str(uuid.uuid4())
        now = utc_now()
        with self._lock, self._connect() as db:
            db.execute(
                """INSERT INTO tasks
                   (id,title,description,agent_name,priority,status,side_effect_level,
                    requires_approval,source,created_at,updated_at,due_at,metadata_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id, title, description, agent_name, priority,
                    "queued", side_effect_level, int(requires_approval), source,
                    now, now, due_at, json.dumps(metadata or {}),
                ),
            )
        self.add_activity("task.created", f"Task created: {title}", task_id=task_id, agent_name=agent_name,
                          payload={"priority": priority, "requires_approval": requires_approval, "source": source})
        if requires_approval:
            self.ensure_approval(task_id)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            return self._row(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM tasks ORDER BY CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        with self._connect() as db:
            counts = {row["status"]: row["count"] for row in db.execute("SELECT status, COUNT(*) AS count FROM tasks GROUP BY status")}
            priority_counts = {row["priority"]: row["count"] for row in db.execute("SELECT priority, COUNT(*) AS count FROM tasks GROUP BY priority")}
            pending = db.execute("SELECT COUNT(*) AS count FROM approvals WHERE status='pending'").fetchone()["count"]
            return {"task_counts": counts, "priority_counts": priority_counts, "approvals_waiting": pending}

    def claim_next_task(self) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                """SELECT * FROM tasks WHERE status='queued' AND (requires_approval=0 OR approval_id IS NOT NULL)
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

    def complete_task(self, task_id: str, result: Any) -> None:
        now = utc_now()
        task = self.get_task(task_id)
        with self._lock, self._connect() as db:
            db.execute("UPDATE tasks SET status='completed', completed_at=?, updated_at=?, result_json=? WHERE id=?", (now, now, json.dumps(result), task_id))
            if task:
                db.execute("UPDATE agent_status SET status='idle', current_task_id=NULL, last_seen_at=? WHERE name=?", (now, task["agent_name"]))
        self.add_activity("task.completed", f"Task completed: {task['title'] if task else task_id}", task_id=task_id,
                          agent_name=task["agent_name"] if task else None)

    def fail_task(self, task_id: str, error: str) -> None:
        now = utc_now()
        task = self.get_task(task_id)
        with self._lock, self._connect() as db:
            db.execute("UPDATE tasks SET status='failed', error=?, updated_at=? WHERE id=?", (error[:2000], now, task_id))
            if task:
                db.execute("UPDATE agent_status SET status='idle', current_task_id=NULL, last_seen_at=? WHERE name=?", (now, task["agent_name"]))
        self.add_activity("task.failed", f"Task failed: {task['title'] if task else task_id}", task_id=task_id,
                          agent_name=task["agent_name"] if task else None, payload={"error": error[:500]})

    def create_exact_approval(
        self,
        request: VerifiedApprovalRequest,
        reason: str = "Verified request approval",
    ) -> dict[str, Any]:
        task = self.get_task(request.task_id)
        if not task:
            raise ValueError("task not found")

        action = approval_action_for_request(request)

        with self._lock, self._connect() as db:
            existing = db.execute(
                "SELECT * FROM approvals "
                "WHERE task_id=? AND action=? AND status='pending'",
                (request.task_id, action),
            ).fetchone()

            if existing:
                approval = dict(existing)
            else:
                approval_id = str(uuid.uuid4())
                now = utc_now()
                db.execute(
                    "INSERT INTO approvals(id,task_id,action,reason,created_at) "
                    "VALUES(?,?,?,?,?)",
                    (approval_id, request.task_id, action, reason, now),
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

    def decide_approval(self, approval_id: str, decision: str, decided_by: str = "local-user") -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        now = utc_now()
        with self._lock, self._connect() as db:
            approval = db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if not approval:
                raise ValueError("approval not found")
            if approval["status"] != "pending":
                return dict(approval)
            db.execute("UPDATE approvals SET status=?, decided_at=?, decided_by=? WHERE id=?", (decision, now, decided_by, approval_id))
            task_status = "queued" if decision == "approved" else "failed"
            error = None if decision == "approved" else "Rejected by human reviewer"
            db.execute("UPDATE tasks SET status=?, error=?, updated_at=? WHERE id=?", (task_status, error, now, approval["task_id"]))
            result = dict(db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone())
        self.add_activity(f"approval.{decision}", f"Approval {decision}: {approval['action']}", task_id=approval["task_id"],
                          payload={"approval_id": approval_id, "decided_by": decided_by})
        return result

    def list_agents(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM agent_status ORDER BY name")]

    def list_activity(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))]

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
