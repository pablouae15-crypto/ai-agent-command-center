from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from store import TaskStore


def make_store(tmp_path: Path) -> TaskStore:
    store = TaskStore(
        db_path=tmp_path / "recurring-jobs.db",
        audit_log_path=tmp_path / "audit.jsonl",
    )
    store.seed_defaults()
    return store


def test_create_job_rejects_interval_below_one_hour(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(ValueError, match="at least 3600"):
        store.create_job(
            name="Too frequent",
            agent_name="Orchestrator",
            prompt="Run too often.",
            interval_seconds=3599,
            next_run_at=datetime.now(timezone.utc).isoformat(),
        )


def test_create_job_rejects_placeholder_agent(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(ValueError, match="not registered"):
        store.create_job(
            name="Disabled updater",
            agent_name="Command Center Updater",
            prompt="Generate a heartbeat.",
            interval_seconds=3600,
            next_run_at=datetime.now(timezone.utc).isoformat(),
        )


def test_due_jobs_returns_enabled_due_jobs_only(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    now = datetime.now(timezone.utc)
    past = (now - timedelta(hours=1)).isoformat()
    future = (now + timedelta(hours=1)).isoformat()

    due = store.create_job(
        name="Due job",
        agent_name="Orchestrator",
        prompt="Run now.",
        interval_seconds=3600,
        next_run_at=past,
    )

    store.create_job(
        name="Future job",
        agent_name="Orchestrator",
        prompt="Run later.",
        interval_seconds=3600,
        next_run_at=future,
    )

    store.create_job(
        name="Disabled job",
        agent_name="Orchestrator",
        prompt="Do not run.",
        interval_seconds=3600,
        next_run_at=past,
        enabled=False,
    )

    rows = store.due_jobs()

    assert [row["id"] for row in rows] == [due["id"]]


def test_advance_job_moves_next_run_into_future(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    job = store.create_job(
        name="Advance job",
        agent_name="Orchestrator",
        prompt="Advance me.",
        interval_seconds=3600,
        next_run_at=past,
    )

    store.advance_job(str(job["id"]), 3600)

    refreshed = next(
        row for row in store.list_jobs()
        if row["id"] == job["id"]
    )

    assert datetime.fromisoformat(refreshed["next_run_at"]) > datetime.now(timezone.utc)

