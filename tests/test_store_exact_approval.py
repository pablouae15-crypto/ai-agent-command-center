from __future__ import annotations

from pathlib import Path

from store import TaskStore
from write_approval import VerifiedEditRequest, approval_action_for_request


def make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(
        db_path=tmp_path / "command-center.db",
        audit_log_path=tmp_path / "audit.jsonl",
    )


def make_task(store: TaskStore) -> dict[str, object]:
    return store.create_task(
        title="Sandbox verified edit",
        description="Test exact-request approval storage.",
        agent_name="Orchestrator",
        requires_approval=False,
    )


def make_request(task_id: str, new_text: str = "return (a + b)") -> VerifiedEditRequest:
    return VerifiedEditRequest(
        task_id=task_id,
        capability="replace_text",
        path=r"D:\Shared-Local-Execution-Engine-Sandbox\app.py",
        repository_path=r"D:\Shared-Local-Execution-Engine-Sandbox",
        verification_profile="sandbox_pytest",
        old_text="return a + b",
        new_text=new_text,
        expected_replacements=1,
    )


def test_create_exact_approval_stores_canonical_action(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))

    approval = store.create_exact_approval(request)

    assert approval["task_id"] == task["id"]
    assert approval["action"] == approval_action_for_request(request)
    assert approval["reason"] == "Verified request approval"
    assert approval["status"] == "pending"


def test_get_approval_returns_exact_stored_row(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    created = store.create_exact_approval(request)

    loaded = store.get_approval(str(created["id"]))

    assert loaded is not None
    assert loaded["id"] == created["id"]
    assert loaded["task_id"] == task["id"]
    assert loaded["action"] == approval_action_for_request(request)


def test_get_approval_returns_none_for_unknown_id(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    assert store.get_approval("missing-approval") is None


def test_same_pending_exact_request_is_reused(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))

    first = store.create_exact_approval(request)
    second = store.create_exact_approval(request)

    assert second["id"] == first["id"]
    assert len(store.list_approvals("pending")) == 1


def test_modified_exact_request_gets_distinct_approval(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    task = make_task(store)

    first_request = make_request(str(task["id"]))
    second_request = make_request(str(task["id"]), new_text="return a + b + 0")

    first = store.create_exact_approval(first_request)
    second = store.create_exact_approval(second_request)

    assert second["id"] != first["id"]
    assert second["action"] != first["action"]
    assert len(store.list_approvals("pending")) == 2


def test_generic_ensure_approval_does_not_reuse_exact_edit_approval(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))

    exact = store.create_exact_approval(request)
    generic = store.ensure_approval(str(task["id"]))

    assert generic["id"] != exact["id"]
    assert generic["action"] == task["title"]
    assert exact["action"] == approval_action_for_request(request)
    assert len(store.list_approvals("pending")) == 2


def test_decided_exact_approval_is_retrievable_with_decision_metadata(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    pending = store.create_exact_approval(request)

    decided = store.decide_approval(
        str(pending["id"]),
        "approved",
        decided_by="test-user",
    )
    loaded = store.get_approval(str(pending["id"]))

    assert decided["status"] == "approved"
    assert loaded is not None
    assert loaded["status"] == "approved"
    assert loaded["decided_by"] == "test-user"
    assert loaded["decided_at"] is not None
