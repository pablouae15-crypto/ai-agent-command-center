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


def _default_title(request: str) -> str:
    compact = " ".join(request.strip().split())

    if not compact:
        return "Personal Assistant Request"

    if len(compact) <= 80:
        return compact

    return compact[:77].rstrip() + "..."



def build_personal_assistant_context(store: TaskStore) -> dict[str, Any]:
    return {
        "summary": store.summary(),
        "agents": store.list_agents(),
        "tasks": store.list_task_visibility(12),
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

    task = store.create_task(
        title=title,
        description=description,
        agent_name="Orchestrator",
        priority=request.priority,
        side_effect_level=request.side_effect_level,
        requires_approval=False,
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
