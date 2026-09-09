from __future__ import annotations

from pathlib import Path

import pytest

import agent
from agent import (
    SPECIALIST_INSTRUCTIONS,
    build_orchestrator,
    build_specialist,
)
from store import TaskStore


def make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(
        db_path=tmp_path / "command-center.db",
        audit_log_path=tmp_path / "audit.jsonl",
    )


@pytest.mark.parametrize(
    "specialist_name",
    ["Developer", "QA", "UIUX", "CodeReviewer"],
)
def test_supported_specialists_build_with_same_safe_tools(
    tmp_path: Path,
    specialist_name: str,
) -> None:
    store = make_store(tmp_path)

    orchestrator = build_orchestrator(
        "gpt-5.6",
        store,
        "task-001",
    )

    specialist = build_specialist(
        specialist_name,
        "gpt-5.6",
        store,
        "task-001",
    )

    assert specialist.name == f"Command Center {specialist_name}"
    assert SPECIALIST_INSTRUCTIONS[specialist_name] in specialist.instructions

    orchestrator_tool_names = [
        tool.name for tool in orchestrator.tools
    ]
    specialist_tool_names = [
        tool.name for tool in specialist.tools
    ]

    assert specialist_tool_names == orchestrator_tool_names

    assert "verified_replace_text" in specialist_tool_names
    assert "verified_write_text_file" in specialist_tool_names

    forbidden_names = {
        "shell",
        "powershell",
        "subprocess",
        "delete",
        "move",
        "rename",
        "deploy",
        "git_push",
        "reset",
        "clean",
        "rebase",
    }

    assert forbidden_names.isdisjoint(specialist_tool_names)


def test_unknown_specialist_is_rejected(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    with pytest.raises(
        ValueError,
        match="Unknown or unauthorized specialist agent",
    ):
        build_specialist(
            "Email / Calendar",
            "gpt-5.6",
            store,
            "task-001",
        )


def test_specialist_registry_contains_only_authorized_developer_roles() -> None:
    assert set(SPECIALIST_INSTRUCTIONS) == {
        "Developer",
        "QA",
        "UIUX",
        "CodeReviewer",
        "Executive Assistant",
    }


def test_runtime_imports_specialist_dispatcher() -> None:
    runtime_text = Path(
        r"D:\AI-Agent-Command-Center\runtime.py"
    ).read_text(encoding="utf-8")

    assert "from agent import run_specialist" in runtime_text
    assert "output = await run_specialist(" in runtime_text
    assert "output = await run_orchestrator(" not in runtime_text


def test_specialist_runner_keeps_ten_turn_limit() -> None:
    source = Path(
        r"D:\AI-Agent-Command-Center\agent.py"
    ).read_text(encoding="utf-8")

    specialist_section = source[
        source.index("async def run_specialist("):
        source.index("async def run_orchestrator(")
    ]

    assert "max_turns=10" in specialist_section


def test_executive_assistant_is_seeded_idle(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.seed_defaults()

    executive = next(
        row for row in store.list_agents()
        if row["name"] == "Executive Assistant"
    )

    assert executive["status"] == "idle"
    assert "coordinates approved work" in executive["description"]


def test_create_and_list_executive_assistant_recurring_job(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.seed_defaults()

    job = store.create_job(
        name="Daily Executive Review",
        agent_name="Executive Assistant",
        prompt="Summarize approved local Command Center activity.",
        interval_seconds=86400,
        next_run_at="2099-01-01T08:00:00+00:00",
    )

    assert job["agent_name"] == "Executive Assistant"
    assert job["interval_seconds"] == 86400
    assert job["enabled"] == 1

    jobs = store.list_jobs()

    saved_job = next(
        row for row in jobs
        if row["id"] == job["id"]
    )

    assert saved_job["name"] == "Daily Executive Review"
    assert saved_job["agent_name"] == "Executive Assistant"
    assert saved_job["interval_seconds"] == 86400


def test_recurring_job_rejects_interval_below_one_hour(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.seed_defaults()

    with pytest.raises(
        ValueError,
        match="at least 3600",
    ):
        store.create_job(
            name="Too Frequent",
            agent_name="Executive Assistant",
            prompt="Run too frequently.",
            interval_seconds=3599,
            next_run_at="2099-01-01T08:00:00+00:00",
        )


def test_recurring_job_rejects_placeholder_agent(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.seed_defaults()

    with pytest.raises(
        ValueError,
        match="not executable",
    ):
        store.create_job(
            name="Email Placeholder Job",
            agent_name="Email / Calendar",
            prompt="Do not execute external email actions.",
            interval_seconds=3600,
            next_run_at="2099-01-01T08:00:00+00:00",
        )


def test_seed_defaults_promotes_existing_placeholder_agent(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.seed_defaults()

    with store._lock, store._connect() as db:
        db.execute(
            "UPDATE agent_status SET status='placeholder' WHERE name=?",
            ("Executive Assistant",),
        )

    before = next(
        row for row in store.list_agents()
        if row["name"] == "Executive Assistant"
    )
    assert before["status"] == "placeholder"

    store.seed_defaults()

    after = next(
        row for row in store.list_agents()
        if row["name"] == "Executive Assistant"
    )
    assert after["status"] == "idle"


def test_seed_defaults_preserves_non_placeholder_runtime_status(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.seed_defaults()

    with store._lock, store._connect() as db:
        db.execute(
            "UPDATE agent_status SET status='working' WHERE name=?",
            ("Developer",),
        )

    store.seed_defaults()

    developer = next(
        row for row in store.list_agents()
        if row["name"] == "Developer"
    )

    assert developer["status"] == "working"


def test_seed_defaults_disables_legacy_placeholder_heartbeat(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.seed_defaults()

    heartbeat = next(
        row for row in store.list_jobs()
        if row["name"] == "command-center-heartbeat"
    )

    assert heartbeat["agent_name"] == "Command Center Updater"
    assert heartbeat["enabled"] == 0
