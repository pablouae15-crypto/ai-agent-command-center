from __future__ import annotations

from pathlib import Path

from store import TaskStore
from write_approval import (
    VerifiedEditBatchRequest,
    VerifiedEditOperation,
    VerifiedEditRequest,
    approval_action_for_request,
)


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


def test_gmail_exact_approval_stores_display_payload(
    tmp_path: Path,
) -> None:
    import json

    from write_approval import VerifiedGmailDraftRequest

    store = make_store(tmp_path)

    task = store.create_task(
        title="Gmail draft approval",
        description="Test Gmail approval display payload.",
        agent_name="Email / Calendar",
        requires_approval=False,
    )

    request = VerifiedGmailDraftRequest(
        task_id=str(task["id"]),
        capability="gmail.draft.create",
        to=("recipient@example.com",),
        cc=("cc@example.com",),
        bcc=("bcc@example.com",),
        subject="Approved Gmail subject",
        body="Approved Gmail body",
    )

    approval = store.create_exact_approval(request)

    payload = json.loads(
        approval["display_payload_json"]
    )

    assert payload == {
        "type": "gmail_draft",
        "to": ["recipient@example.com"],
        "cc": ["cc@example.com"],
        "bcc": ["bcc@example.com"],
        "subject": "Approved Gmail subject",
        "body": "Approved Gmail body",
    }

    assert approval["action"] == approval_action_for_request(
        request
    )


def test_verified_edit_exact_approval_persists_execution_payload(
    tmp_path: Path,
) -> None:
    import json

    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))

    approval = store.create_exact_approval(request)

    payload = json.loads(
        approval["display_payload_json"]
    )

    assert payload == {
        "type": "verified_edit_execution",
        "capability": "replace_text",
        "path": request.path,
        "repository_path": request.repository_path,
        "verification_profile": request.verification_profile,
        "old_text": request.old_text,
        "new_text": request.new_text,
        "expected_replacements": request.expected_replacements,
    }


def test_gmail_execution_is_idempotent_by_approval_id(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    approval = store.create_exact_approval(request)

    first = store.begin_gmail_draft_execution(
        str(approval["id"]),
        str(task["id"]),
    )

    second = store.begin_gmail_draft_execution(
        str(approval["id"]),
        str(task["id"]),
    )

    assert first["status"] == "creating"
    assert second["status"] == "creating"
    assert second["approval_id"] == first["approval_id"]


def test_gmail_execution_can_complete_once(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    approval = store.create_exact_approval(request)

    store.begin_gmail_draft_execution(
        str(approval["id"]),
        str(task["id"]),
    )

    completed = store.complete_gmail_draft_execution(
        str(approval["id"]),
        "draft-123",
        "message-456",
    )

    repeated = store.complete_gmail_draft_execution(
        str(approval["id"]),
        "draft-999",
        "message-999",
    )

    assert completed["status"] == "created"
    assert completed["gmail_draft_id"] == "draft-123"
    assert completed["gmail_message_id"] == "message-456"

    assert repeated["status"] == "created"
    assert repeated["gmail_draft_id"] == "draft-123"
    assert repeated["gmail_message_id"] == "message-456"


def test_failed_gmail_execution_does_not_restart_automatically(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    approval = store.create_exact_approval(request)

    store.begin_gmail_draft_execution(
        str(approval["id"]),
        str(task["id"]),
    )

    failed = store.fail_gmail_draft_execution(
        str(approval["id"]),
        "ambiguous Gmail API failure",
    )

    repeated = store.begin_gmail_draft_execution(
        str(approval["id"]),
        str(task["id"]),
    )

    assert failed["status"] == "failed"
    assert repeated["status"] == "failed"
    assert repeated["error"] == "ambiguous Gmail API failure"


def test_approved_generic_approval_is_replaced_by_exact_verified_approval(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    task = store.create_task(
        title="Sandbox verified edit",
        description="Test generic approval promotion.",
        agent_name="Orchestrator",
        requires_approval=True,
        side_effect_level="external",
    )

    generic = store.ensure_approval(str(task["id"]))

    decided_generic = store.decide_approval(
        str(generic["id"]),
        "approved",
        decided_by="test-user",
    )

    assert decided_generic["status"] == "approved"

    request = make_request(str(task["id"]))

    exact = store.create_exact_approval(request)

    refreshed_task = store.get_task(str(task["id"]))

    assert exact["id"] != generic["id"]
    assert exact["action"] == approval_action_for_request(request)
    assert exact["status"] == "pending"

    assert refreshed_task is not None
    assert refreshed_task["approval_id"] == exact["id"]
    assert refreshed_task["status"] == "awaiting_approval"

    loaded_generic = store.get_approval(str(generic["id"]))
    assert loaded_generic is not None
    assert loaded_generic["status"] == "superseded"

def test_stale_pending_approval_cannot_revive_completed_task(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    task = store.create_task(
        title="Stale approval protection",
        description="Verify a late approval cannot revive completed work.",
        agent_name="Developer",
        requires_approval=True,
        side_effect_level="external",
    )

    stale = store.ensure_approval(str(task["id"]))

    store.complete_task(
        str(task["id"]),
        {"output": "verified successful execution"},
    )

    decided = store.decide_approval(
        str(stale["id"]),
        "approved",
        decided_by="test-user",
    )

    refreshed_task = store.get_task(str(task["id"]))

    assert refreshed_task is not None
    assert refreshed_task["status"] == "completed"
    assert refreshed_task["result_json"] is not None
    assert refreshed_task["completed_at"] is not None
    assert refreshed_task["error"] is None

    assert decided["status"] == "superseded"

def test_blocked_task_matching_exact_approval_can_be_approved(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))

    pending = store.create_exact_approval(
        request,
        reason="Execute this exact verified edit",
    )
    store.block_task(
        str(task["id"]),
        "Exact verified edit is waiting for human approval.",
    )

    decided = store.decide_approval(
        str(pending["id"]),
        "approved",
        decided_by="test-user",
    )
    refreshed_task = store.get_task(str(task["id"]))

    assert decided["status"] == "approved"
    assert refreshed_task is not None
    assert refreshed_task["status"] == "queued"
    assert refreshed_task["approval_id"] == pending["id"]
    assert refreshed_task["error"] is None

def test_verified_edit_batch_exact_approval_persists_execution_payload(
    tmp_path: Path,
) -> None:
    import json

    store = make_store(tmp_path)
    task = make_task(store)

    request = VerifiedEditBatchRequest(
        task_id=str(task["id"]),
        capability="replace_text_batch",
        repository_path=r"D:\Shared-Local-Execution-Engine-Sandbox",
        verification_profile="sandbox_pytest",
        edits=(
            VerifiedEditOperation(
                path=r"D:\Shared-Local-Execution-Engine-Sandbox\app.py",
                old_text="return a - b",
                new_text="return a + b",
                expected_replacements=1,
            ),
            VerifiedEditOperation(
                path=r"D:\Shared-Local-Execution-Engine-Sandbox\test_app.py",
                old_text="assert add(2, 3) == -1",
                new_text="assert add(2, 3) == 5",
                expected_replacements=1,
            ),
        ),
    )

    approval = store.create_exact_approval(request)

    payload = json.loads(approval["display_payload_json"])

    assert payload == {
        "type": "verified_edit_batch_execution",
        "capability": "replace_text_batch",
        "repository_path": request.repository_path,
        "verification_profile": request.verification_profile,
        "edits": [
            {
                "path": request.edits[0].path,
                "old_text": request.edits[0].old_text,
                "new_text": request.edits[0].new_text,
                "expected_replacements": 1,
            },
            {
                "path": request.edits[1].path,
                "old_text": request.edits[1].old_text,
                "new_text": request.edits[1].new_text,
                "expected_replacements": 1,
            },
        ],
    }

    assert approval["action"] == approval_action_for_request(request)
