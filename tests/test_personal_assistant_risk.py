from fastapi.testclient import TestClient

import main


def test_read_only_status_request_is_not_classified_as_external() -> None:
    request = (
        "Give me a short status summary of the AI Agent Command Center. "
        "Do not modify files, run commands, or call external services."
    )

    assert main.classify_task_side_effect("", request) == "none"


def test_personal_assistant_handoff_classifies_file_edit_as_external(
    monkeypatch,
) -> None:
    captured = {}

    class FakeResult:
        def model_dump(self):
            return {
                "task_id": "test-task",
                "title": "Edit file",
                "status": "awaiting_approval",
                "agent_name": "Orchestrator",
                "priority": "Medium",
                "side_effect_level": "external",
                "requires_approval": True,
                "approval_id": "approval-1",
            }

    def fake_handoff(store, request):
        captured["side_effect_level"] = request.side_effect_level
        return FakeResult()

    monkeypatch.setattr(
        main,
        "handoff_to_command_center",
        fake_handoff,
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/assistant/handoff",
            json={
                "request": (
                    "Edit D:\\Shared-Local-Execution-Engine-Sandbox\\app.py "
                    "and replace return a + b with return a - b."
                ),
                "priority": "Medium",
            },
        )

    assert response.status_code == 201
    assert captured["side_effect_level"] == "external"
