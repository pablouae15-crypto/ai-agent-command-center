from fastapi.testclient import TestClient

import main


def test_manual_file_edit_is_classified_as_external_and_requires_approval(monkeypatch):
    captured = {}

    def fake_create_task(**kwargs):
        captured.update(kwargs)
        return {
            "id": "test-task",
            "title": kwargs["title"],
            "status": "awaiting_approval",
            "side_effect_level": kwargs["side_effect_level"],
            "requires_approval": True,
        }

    monkeypatch.setattr(main.store, "create_task", fake_create_task)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/tasks",
            json={
                "title": "Modify sandbox file",
                "description": (
                    r'In D:\Shared-Local-Execution-Engine-Sandbox\app.py, '
                    r'replace exactly "return a + b" with "return a - b".'
                ),
                "priority": "Medium",
            },
        )

    assert response.status_code == 201
    assert captured["side_effect_level"] == "external"
    assert captured["requires_approval"] is True

def test_read_only_file_inspection_is_none_and_does_not_require_approval(monkeypatch):
    captured = {}

    def fake_create_task(**kwargs):
        captured.update(kwargs)
        return {
            "id": "test-task",
            "title": kwargs["title"],
            "status": "queued",
            "side_effect_level": kwargs["side_effect_level"],
            "requires_approval": kwargs["requires_approval"],
        }

    monkeypatch.setattr(main.store, "create_task", fake_create_task)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/tasks",
            json={
                "title": "Inspect sandbox file",
                "description": (
                    r'Read D:\Shared-Local-Execution-Engine-Sandbox\app.py '
                    r'and report whether the function exists. Do not modify any files.'
                ),
                "priority": "Medium",
            },
        )

    assert response.status_code == 201
    assert captured["side_effect_level"] == "none"
    assert captured["requires_approval"] is False
