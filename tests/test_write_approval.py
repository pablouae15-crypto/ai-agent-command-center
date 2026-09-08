from datetime import datetime, timezone

import pytest

from write_approval import (
    VerifiedEditRequest,
    approval_action_for_request,
    validate_stored_approval,
)


def make_request() -> VerifiedEditRequest:
    return VerifiedEditRequest(
        task_id="task-001",
        capability="replace_text",
        path=r"D:\Shared-Local-Execution-Engine-Sandbox\app.py",
        repository_path=r"D:\Shared-Local-Execution-Engine-Sandbox",
        verification_profile="sandbox_pytest",
        old_text="return a + b",
        new_text="return (a + b)",
        expected_replacements=1,
    )


def make_approved_row(request: VerifiedEditRequest) -> dict[str, object]:
    return {
        "id": "approval-001",
        "task_id": request.task_id,
        "action": approval_action_for_request(request),
        "reason": "Verified edit approval",
        "status": "approved",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "decided_by": "test-user",
    }


def test_fingerprint_is_stable() -> None:
    request = make_request()

    assert request.fingerprint() == request.fingerprint()


def test_fingerprint_changes_when_new_text_changes() -> None:
    request_a = make_request()

    request_b = VerifiedEditRequest(
        task_id=request_a.task_id,
        capability=request_a.capability,
        path=request_a.path,
        repository_path=request_a.repository_path,
        verification_profile=request_a.verification_profile,
        old_text=request_a.old_text,
        new_text="return a - b",
        expected_replacements=request_a.expected_replacements,
    )

    assert request_a.fingerprint() != request_b.fingerprint()


def test_fingerprint_changes_when_path_changes() -> None:
    request_a = make_request()

    request_b = VerifiedEditRequest(
        task_id=request_a.task_id,
        capability=request_a.capability,
        path=r"D:\Shared-Local-Execution-Engine-Sandbox\other.py",
        repository_path=request_a.repository_path,
        verification_profile=request_a.verification_profile,
        old_text=request_a.old_text,
        new_text=request_a.new_text,
        expected_replacements=request_a.expected_replacements,
    )

    assert request_a.fingerprint() != request_b.fingerprint()


def test_valid_stored_approval_returns_approval_record() -> None:
    request = make_request()
    row = make_approved_row(request)

    approval = validate_stored_approval(row, request)

    assert approval.approval_id == "approval-001"
    assert approval.task_id == request.task_id
    assert approval.capability == "replace_text"
    assert approval.status == "approved"
    assert approval.decided_by == "test-user"


def test_pending_approval_is_rejected() -> None:
    request = make_request()
    row = make_approved_row(request)
    row["status"] = "pending"

    with pytest.raises(PermissionError):
        validate_stored_approval(row, request)


def test_wrong_task_is_rejected() -> None:
    request = make_request()
    row = make_approved_row(request)
    row["task_id"] = "different-task"

    with pytest.raises(PermissionError):
        validate_stored_approval(row, request)


def test_modified_new_text_invalidates_approval() -> None:
    original_request = make_request()
    row = make_approved_row(original_request)

    modified_request = VerifiedEditRequest(
        task_id=original_request.task_id,
        capability=original_request.capability,
        path=original_request.path,
        repository_path=original_request.repository_path,
        verification_profile=original_request.verification_profile,
        old_text=original_request.old_text,
        new_text="return a - b",
        expected_replacements=original_request.expected_replacements,
    )

    with pytest.raises(PermissionError):
        validate_stored_approval(row, modified_request)


def test_modified_path_invalidates_approval() -> None:
    original_request = make_request()
    row = make_approved_row(original_request)

    modified_request = VerifiedEditRequest(
        task_id=original_request.task_id,
        capability=original_request.capability,
        path=r"D:\Shared-Local-Execution-Engine-Sandbox\other.py",
        repository_path=original_request.repository_path,
        verification_profile=original_request.verification_profile,
        old_text=original_request.old_text,
        new_text=original_request.new_text,
        expected_replacements=original_request.expected_replacements,
    )

    with pytest.raises(PermissionError):
        validate_stored_approval(row, modified_request)


def test_missing_decision_actor_is_rejected() -> None:
    request = make_request()
    row = make_approved_row(request)
    row["decided_by"] = None

    with pytest.raises(PermissionError):
        validate_stored_approval(row, request)


def test_missing_decision_timestamp_is_rejected() -> None:
    request = make_request()
    row = make_approved_row(request)
    row["decided_at"] = None

    with pytest.raises(PermissionError):
        validate_stored_approval(row, request)