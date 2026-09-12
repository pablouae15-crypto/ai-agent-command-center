import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from store import TaskStore


class PersonalAssistantRequest(BaseModel):
    request: str = Field(min_length=1, max_length=10000)
    title: str | None = Field(default=None, max_length=200)
    priority: Literal["Critical", "High", "Medium", "Low"] = "Medium"
    side_effect_level: Literal["none", "external", "destructive"] = "none"


class PersonalAssistantHandoffResult(BaseModel):
    task_id: str
    title: str
    status: str
    agent_name: str
    priority: str
    side_effect_level: str
    requires_approval: bool
    approval_id: str | None = None


def should_defer_exact_approval(request_text: str) -> bool:
    """Return true when a handoff should wait for an exact verified approval."""
    content = request_text.lower()
    verified_execution_markers = (
        "use verified replace text",
        "verified replace text",
        "verified_replace_text",
        "use verified write text file",
        "verified write text file",
        "verified_write_text_file",
    )
    return any(marker in content for marker in verified_execution_markers)


def _default_title(request: str) -> str:
    compact = " ".join(request.strip().split())

    if not compact:
        return "Personal Assistant Request"

    if len(compact) <= 80:
        return compact

    return compact[:77].rstrip() + "..."



def build_personal_assistant_context(store: TaskStore) -> dict[str, Any]:
    visible_tasks = store.list_task_visibility(12)

    compact_tasks = [
        {
            "id": task.get("id"),
            "title": task.get("title"),
            "agent_name": task.get("agent_name"),
            "priority": task.get("priority"),
            "status": task.get("status"),
            "side_effect_level": task.get("side_effect_level"),
            "requires_approval": bool(task.get("requires_approval")),
            "approval_id": task.get("approval_id"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "routed_specialist": task.get("routed_specialist"),
            "routing_reason": task.get("routing_reason"),
            "latest_activity_type": task.get("latest_activity_type"),
            "latest_activity_at": task.get("latest_activity_at"),
        }
        for task in visible_tasks
    ]

    return {
        "summary": store.summary(),
        "agents": store.list_agents(),
        "tasks": compact_tasks,
        "approvals": store.list_approvals(),
        "activity": store.list_activity(15),
    }


def _assistant_description(
    original_request: str,
    command_center_context: dict[str, Any],
) -> str:
    context_json = json.dumps(
        command_center_context,
        ensure_ascii=False,
        default=str,
        indent=2,
    )

    return (
        "USER REQUEST\n"
        f"{original_request.strip()}\n\n"
        "CURRENT COMMAND CENTER CONTEXT\n"
        "Use this context as current system evidence. "
        "Do not invent project state beyond this snapshot. "
        "If required evidence is missing, state that clearly.\n\n"
        f"{context_json}"
    )


def _parse_verified_edit_batch_request(request_text: str) -> dict | None:
    import re

    def field(label: str, section: str) -> str | None:
        match = re.search(
            rf"(?im)^\s*{re.escape(label)}:\s*(.*)$",
            section,
        )
        return match.group(1).rstrip() if match else None

    capability = field("Capability", request_text)
    repository_path = field("Repository path", request_text)
    verification_profile = field("Verification profile", request_text)

    if capability != "replace_text_batch":
        return None
    if not repository_path or not verification_profile:
        return None

    sections = re.split(
        r"(?im)^\s*Edit\s+\d+\s*:\s*$",
        request_text,
    )[1:]

    edits = []
    for section in sections:
        path = field("Path", section)
        old_text = field("Old text", section)
        new_text = field("New text", section)
        expected = field("Expected replacements", section)

        if (
            not path
            or old_text is None
            or new_text is None
            or expected is None
        ):
            return None

        try:
            expected_replacements = int(expected)
        except ValueError:
            return None

        if expected_replacements < 1:
            return None

        edits.append(
            {
                "path": path,
                "old_text": old_text,
                "new_text": new_text,
                "expected_replacements": expected_replacements,
            }
        )

    if not edits:
        return None

    return {
        "capability": capability,
        "repository_path": repository_path,
        "verification_profile": verification_profile,
        "edits": edits,
    }


def handoff_to_command_center(
    store: TaskStore,
    request: PersonalAssistantRequest,
) -> PersonalAssistantHandoffResult:
    """
    Submit Personal AI Assistant work to the Command Center.

    The Personal Assistant cannot select a specialist directly.
    All delegated work enters through the Orchestrator so routing,
    approval controls, audit logging, and execution boundaries remain
    authoritative.
    """

    original_request = request.request.strip()
    command_center_context = build_personal_assistant_context(store)

    description = _assistant_description(
        original_request,
        command_center_context,
    )

    title = (
        request.title.strip()
        if request.title and request.title.strip()
        else _default_title(original_request)
    )

    batch_payload = _parse_verified_edit_batch_request(original_request)

    if batch_payload is not None:
        from write_approval import (
            VerifiedEditBatchRequest,
            VerifiedEditOperation,
        )

        batch_task = store.create_task(
            title=title,
            description=description,
            agent_name="Orchestrator",
            priority=request.priority,
            side_effect_level=request.side_effect_level,
            requires_approval=False,
            defer_exact_approval=True,
            source="personal-assistant",
            metadata={
                "workflow_type": "personal_assistant_handoff",
                "submitted_by": "Personal AI Assistant",
                "original_request": original_request,
                "command_center_context": command_center_context,
            },
        )

        operations = tuple(
            VerifiedEditOperation(**edit)
            for edit in batch_payload["edits"]
        )

        exact_request = VerifiedEditBatchRequest(
            task_id=str(batch_task["id"]),
            capability=batch_payload["capability"],
            repository_path=batch_payload["repository_path"],
            verification_profile=batch_payload["verification_profile"],
            edits=operations,
        )

        approval = store.create_exact_approval(
            exact_request,
            reason="Execute this exact verified edit batch",
        )

        batch_task = store.get_task(str(batch_task["id"])) or batch_task

        return PersonalAssistantHandoffResult(
            task_id=str(batch_task["id"]),
            title=str(batch_task["title"]),
            status=str(batch_task["status"]),
            agent_name=str(batch_task["agent_name"]),
            priority=str(batch_task["priority"]),
            side_effect_level=str(batch_task["side_effect_level"]),
            requires_approval=bool(batch_task["requires_approval"]),
            approval_id=str(approval["id"]),
        )

    task = store.create_task(
        title=title,
        description=description,
        agent_name="Orchestrator",
        priority=request.priority,
        side_effect_level=request.side_effect_level,
        requires_approval=False,
        defer_exact_approval=should_defer_exact_approval(original_request),
        source="personal-assistant",
        metadata={
            "workflow_type": "personal_assistant_handoff",
            "submitted_by": "Personal AI Assistant",
            "original_request": original_request,
            "command_center_context": command_center_context,
        },
    )

    return PersonalAssistantHandoffResult(
        task_id=str(task["id"]),
        title=str(task["title"]),
        status=str(task["status"]),
        agent_name=str(task["agent_name"]),
        priority=str(task["priority"]),
        side_effect_level=str(task["side_effect_level"]),
        requires_approval=bool(task["requires_approval"]),
        approval_id=(
            str(task["approval_id"])
            if task.get("approval_id")
            else None
        ),
    )
