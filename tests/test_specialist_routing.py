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
            "Executive Assistant",
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
