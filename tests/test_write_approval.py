from datetime import datetime, timezone

import pytest

from write_approval import (
    VerifiedEditBatchRequest,
    VerifiedEditOperation,
    VerifiedEditRequest,
    VerifiedFileWriteRequest,
    VerifiedGmailDraftRequest,
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


def make_file_write_request(
    *,
    content: str = "def add(a, b):\n    return a + b\n",
    expected_sha256: str = "a" * 64,
    path: str = r"D:\Shared-Local-Execution-Engine-Sandbox\app.py",
) -> VerifiedFileWriteRequest:
    return VerifiedFileWriteRequest(
        task_id="task-file-write-001",
        capability="write_text_file",
        path=path,
        repository_path=r"D:\Shared-Local-Execution-Engine-Sandbox",
        verification_profile="sandbox_pytest",
        content=content,
        expected_sha256=expected_sha256,
    )


def make_approved_file_write_row(
    request: VerifiedFileWriteRequest,
) -> dict[str, object]:
    return {
        "id": "approval-file-write-001",
        "task_id": request.task_id,
        "action": approval_action_for_request(request),
        "status": "approved",
        "decided_at": "2026-09-09T00:00:00+00:00",
        "decided_by": "test-user",
    }


def test_file_write_approval_uses_distinct_action_type() -> None:
    request = make_file_write_request()

    action = approval_action_for_request(request)

    assert '"type":"verified_file_write"' in action
    assert '"content_sha256"' in action
    assert '"expected_sha256"' in action


def test_exact_file_write_approval_validates() -> None:
    request = make_file_write_request()
    row = make_approved_file_write_row(request)

    approval = validate_stored_approval(row, request)

    assert approval.task_id == request.task_id
    assert approval.capability == "write_text_file"
    assert approval.status == "approved"


def test_modified_file_content_invalidates_approval() -> None:
    original = make_file_write_request()
    row = make_approved_file_write_row(original)

    modified = make_file_write_request(
        content="def add(a, b):\n    return a - b\n",
    )

    with pytest.raises(PermissionError):
        validate_stored_approval(row, modified)


def test_modified_expected_sha256_invalidates_file_write_approval() -> None:
    original = make_file_write_request()
    row = make_approved_file_write_row(original)

    modified = make_file_write_request(
        expected_sha256="b" * 64,
    )

    with pytest.raises(PermissionError):
        validate_stored_approval(row, modified)


def test_modified_file_write_path_invalidates_approval() -> None:
    original = make_file_write_request()
    row = make_approved_file_write_row(original)

    modified = make_file_write_request(
        path=r"D:\Shared-Local-Execution-Engine-Sandbox\other.py",
    )

    with pytest.raises(PermissionError):
        validate_stored_approval(row, modified)


def make_gmail_draft_request(
    *,
    task_id: str = "task-gmail-001",
    capability: str = "gmail.draft.create",
    to: tuple[str, ...] = ("recipient@example.com",),
    subject: str = "Test subject",
    body: str = "Test body",
    cc: tuple[str, ...] = (),
    bcc: tuple[str, ...] = (),
) -> VerifiedGmailDraftRequest:
    return VerifiedGmailDraftRequest(
        task_id=task_id,
        capability=capability,
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
    )


def make_approved_gmail_draft_row(
    request: VerifiedGmailDraftRequest,
) -> dict[str, object]:
    return {
        "id": "approval-gmail-001",
        "task_id": request.task_id,
        "action": approval_action_for_request(request),
        "reason": "Verified Gmail draft approval",
        "status": "approved",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "decided_by": "test-user",
    }


def test_exact_gmail_draft_approval_validates() -> None:
    request = make_gmail_draft_request()
    row = make_approved_gmail_draft_row(request)

    approval = validate_stored_approval(row, request)

    assert approval.task_id == request.task_id
    assert approval.capability == "gmail.draft.create"
    assert approval.status == "approved"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("to", ("other@example.com",)),
        ("subject", "Changed subject"),
        ("body", "Changed body"),
        ("cc", ("cc@example.com",)),
        ("bcc", ("bcc@example.com",)),
        ("capability", "gmail.other"),
    ],
)
def test_modified_gmail_draft_invalidates_approval(
    field: str,
    value: object,
) -> None:
    original = make_gmail_draft_request()
    row = make_approved_gmail_draft_row(original)

    kwargs = {
        "task_id": original.task_id,
        "capability": original.capability,
        "to": original.to,
        "subject": original.subject,
        "body": original.body,
        "cc": original.cc,
        "bcc": original.bcc,
    }
    kwargs[field] = value

    modified = VerifiedGmailDraftRequest(**kwargs)

    with pytest.raises(PermissionError):
        validate_stored_approval(row, modified)


def test_gmail_draft_body_is_hashed_in_canonical_payload() -> None:
    request = make_gmail_draft_request()

    payload = request.canonical_payload()

    assert "body" not in payload
    assert "body_sha256" in payload
    assert payload["body_sha256"]


def test_gmail_draft_action_type_is_distinct() -> None:
    request = make_gmail_draft_request()

    action = approval_action_for_request(request)

    assert '"type":"verified_gmail_draft"' in action

def make_batch_request(
    *,
    edits: tuple[VerifiedEditOperation, ...] | None = None,
) -> VerifiedEditBatchRequest:
    if edits is None:
        edits = (
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
        )

    return VerifiedEditBatchRequest(
        task_id="task-batch-001",
        capability="replace_text_batch",
        repository_path=r"D:\Shared-Local-Execution-Engine-Sandbox",
        verification_profile="sandbox_pytest",
        edits=edits,
    )


def test_batch_approval_uses_distinct_action_type() -> None:
    request = make_batch_request()

    action = approval_action_for_request(request)

    assert '"type":"verified_edit_batch"' in action
    assert '"capability":"replace_text_batch"' in action
    assert '"edits":[' in action


def test_exact_batch_approval_validates() -> None:
    request = make_batch_request()
    row = {
        "id": "approval-batch-001",
        "task_id": request.task_id,
        "action": approval_action_for_request(request),
        "status": "approved",
        "decided_at": "2026-09-12T00:00:00+00:00",
        "decided_by": "test-user",
    }

    approval = validate_stored_approval(row, request)

    assert approval.task_id == request.task_id
    assert approval.capability == "replace_text_batch"
    assert approval.status == "approved"


def test_modified_batch_edit_text_invalidates_approval() -> None:
    original = make_batch_request()
    row = {
        "id": "approval-batch-001",
        "task_id": original.task_id,
        "action": approval_action_for_request(original),
        "status": "approved",
        "decided_at": "2026-09-12T00:00:00+00:00",
        "decided_by": "test-user",
    }

    modified = make_batch_request(
        edits=(
            original.edits[0],
            VerifiedEditOperation(
                path=original.edits[1].path,
                old_text=original.edits[1].old_text,
                new_text="assert add(2, 3) == 6",
                expected_replacements=1,
            ),
        ),
    )

    with pytest.raises(PermissionError):
        validate_stored_approval(row, modified)


def test_modified_batch_path_invalidates_approval() -> None:
    original = make_batch_request()
    row = {
        "id": "approval-batch-001",
        "task_id": original.task_id,
        "action": approval_action_for_request(original),
        "status": "approved",
        "decided_at": "2026-09-12T00:00:00+00:00",
        "decided_by": "test-user",
    }

    modified = make_batch_request(
        edits=(
            VerifiedEditOperation(
                path=r"D:\Shared-Local-Execution-Engine-Sandbox\other.py",
                old_text=original.edits[0].old_text,
                new_text=original.edits[0].new_text,
                expected_replacements=1,
            ),
            original.edits[1],
        ),
    )

    with pytest.raises(PermissionError):
        validate_stored_approval(row, modified)


def test_reordered_batch_invalidates_approval() -> None:
    original = make_batch_request()
    row = {
        "id": "approval-batch-001",
        "task_id": original.task_id,
        "action": approval_action_for_request(original),
        "status": "approved",
        "decided_at": "2026-09-12T00:00:00+00:00",
        "decided_by": "test-user",
    }

    reordered = make_batch_request(
        edits=(original.edits[1], original.edits[0]),
    )

    with pytest.raises(PermissionError):
        validate_stored_approval(row, reordered)


def test_extra_batch_edit_invalidates_approval() -> None:
    original = make_batch_request()
    row = {
        "id": "approval-batch-001",
        "task_id": original.task_id,
        "action": approval_action_for_request(original),
        "status": "approved",
        "decided_at": "2026-09-12T00:00:00+00:00",
        "decided_by": "test-user",
    }

    expanded = make_batch_request(
        edits=original.edits
        + (
            VerifiedEditOperation(
                path=r"D:\Shared-Local-Execution-Engine-Sandbox\helper.py",
                old_text="OLD",
                new_text="NEW",
                expected_replacements=1,
            ),
        ),
    )

    with pytest.raises(PermissionError):
        validate_stored_approval(row, expanded)
