from fastapi.testclient import TestClient

import main


class FakeExecutionEngine:
    ready = True

    def list_directory(self, path, *, task_id=None):
        return [{"name": "README.md", "path": str(path), "task_id": task_id}]


def test_execution_request_list_directory_uses_adapter(monkeypatch) -> None:
    monkeypatch.setattr(main, "execution_engine", FakeExecutionEngine())

    with TestClient(main.app) as client:
        response = client.post(
            "/api/execution/request",
            json={
                "capability": "list_directory",
                "path": r"D:\AI-Agent-Command-Center",
                "task_id": "task-123",
            },
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "README.md",
            "path": r"D:\AI-Agent-Command-Center",
            "task_id": "task-123",
        }
    ]


def test_execution_request_requires_ready_engine(monkeypatch) -> None:
    fake = FakeExecutionEngine()
    fake.ready = False
    monkeypatch.setattr(main, "execution_engine", fake)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/execution/request",
            json={
                "capability": "list_directory",
                "path": r"D:\AI-Agent-Command-Center",
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Shared Local Execution Engine is disabled or not ready."
    )


def test_execution_request_validates_required_fields(monkeypatch) -> None:
    monkeypatch.setattr(main, "execution_engine", FakeExecutionEngine())

    with TestClient(main.app) as client:
        response = client.post(
            "/api/execution/request",
            json={"capability": "list_directory"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "path is required."
