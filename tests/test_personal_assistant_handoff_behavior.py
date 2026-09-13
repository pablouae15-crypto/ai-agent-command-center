from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, r'D:\Shared-Local-Execution-Engine')

from personal_assistant import (
    AssistantContextLimitExceeded,
    PersonalAssistantRequest,
    handoff_to_command_center,
)
from store import TaskStore


def make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(
        tmp_path / "command_center.db",
        tmp_path / "audit.jsonl",
    )


def test_personal_assistant_handoff_creates_orchestrator_task_with_context(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    result = handoff_to_command_center(
        store,
        PersonalAssistantRequest(
            request="Summarize the current command center status.",
            priority="High",
        ),
    )

    task = store.get_task(result.task_id)

    assert task is not None
    assert result.title == "Summarize the current command center status."
    assert task["agent_name"] == "Orchestrator"
    assert task["priority"] == "High"
    assert task["source"] == "personal-assistant"
    assert "CURRENT COMMAND CENTER CONTEXT" in task["description"]
    assert "Summarize the current command center status." in task["description"]


def test_personal_assistant_handoff_defers_verified_edit_until_exact_approval(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    result = handoff_to_command_center(
        store,
        PersonalAssistantRequest(
            request="Use verified replace text in the sandbox file.",
        ),
    )

    task = store.get_task(result.task_id)

    assert task is not None
    assert task["status"] == "queued"
    assert task["approval_id"] is None
    assert result.requires_approval is False


def test_personal_assistant_handoff_defers_approved_replacement_paraphrase(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    result = handoff_to_command_center(
        store,
        PersonalAssistantRequest(
            request="Apply an approved text replacement in the sandbox file.",
        ),
    )

    task = store.get_task(result.task_id)

    assert task is not None
    assert task["status"] == "queued"
    assert task["approval_id"] is None
    assert result.requires_approval is False


def test_personal_assistant_handoff_keeps_unapproved_edit_on_normal_approval_path(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    result = handoff_to_command_center(
        store,
        PersonalAssistantRequest(
            request="Edit the sandbox file and replace the old text.",
            side_effect_level="external",
        ),
    )

    task = store.get_task(result.task_id)

    assert task is not None
    assert task["status"] == "awaiting_approval"
    assert task["approval_id"] is not None
    assert result.requires_approval is True


def test_personal_assistant_handoff_rejects_oversized_context_before_task_creation(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    with pytest.raises(AssistantContextLimitExceeded, match="No task was created"):
        handoff_to_command_center(
            store,
            PersonalAssistantRequest(request="x" * 500),
            max_description_chars=100,
        )

    assert store.list_tasks() == []

def test_parse_verified_edit_batch_request_preserves_multiline_new_text() -> None:
    from personal_assistant import _parse_verified_edit_batch_request

    request_text = "\n".join(
        [
            "*Capability: replace_text_batch",
            r"*Repository path: D:\AI-Agent-Command-Center",
            "*Verification profile: sandbox_pytest",
            "Edit 1:",
            r"*Path: D:\AI-Agent-Command-Center\execution_adapter.py",
            "*Old text: return self._engine",
            "*New text: assert self._engine is not None",
            "        return self._engine",
            "*Expected replacements: 1",
        ]
    )

    parsed = _parse_verified_edit_batch_request(request_text)

    assert parsed is not None
    assert parsed["capability"] == "replace_text_batch"
    assert parsed["repository_path"] == r"D:\AI-Agent-Command-Center"
    assert parsed["verification_profile"] == "sandbox_pytest"
    assert "Edit 1:" not in parsed["verification_profile"]

    edit = parsed["edits"][0]

    assert edit["new_text"] == (
        "assert self._engine is not None\n"
        "        return self._engine"
    )
    assert edit["expected_replacements"] == 1





