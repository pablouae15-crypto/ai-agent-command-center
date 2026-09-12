from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from engine.approvals import ApprovalRecord


@dataclass(frozen=True)
class VerifiedEditOperation:
    path: str
    old_text: str
    new_text: str
    expected_replacements: int = 1

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "old_text_sha256": hashlib.sha256(
                self.old_text.encode("utf-8")
            ).hexdigest(),
            "new_text_sha256": hashlib.sha256(
                self.new_text.encode("utf-8")
            ).hexdigest(),
            "expected_replacements": self.expected_replacements,
        }


@dataclass(frozen=True)
class VerifiedEditBatchRequest:
    task_id: str
    capability: str
    repository_path: str
    verification_profile: str
    edits: tuple[VerifiedEditOperation, ...]

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "capability": self.capability,
            "repository_path": self.repository_path,
            "verification_profile": self.verification_profile,
            "edits": [
                edit.canonical_payload()
                for edit in self.edits
            ],
        }

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class VerifiedEditRequest:
    task_id: str
    capability: str
    path: str
    repository_path: str
    verification_profile: str
    old_text: str
    new_text: str
    expected_replacements: int = 1

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "capability": self.capability,
            "path": self.path,
            "repository_path": self.repository_path,
            "verification_profile": self.verification_profile,
            "old_text_sha256": hashlib.sha256(
                self.old_text.encode("utf-8")
            ).hexdigest(),
            "new_text_sha256": hashlib.sha256(
                self.new_text.encode("utf-8")
            ).hexdigest(),
            "expected_replacements": self.expected_replacements,
        }

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class VerifiedFileWriteRequest:
    task_id: str
    capability: str
    path: str
    repository_path: str
    verification_profile: str
    content: str
    expected_sha256: str

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "capability": self.capability,
            "path": self.path,
            "repository_path": self.repository_path,
            "verification_profile": self.verification_profile,
            "content_sha256": hashlib.sha256(
                self.content.encode("utf-8")
            ).hexdigest(),
            "expected_sha256": self.expected_sha256,
        }

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class VerifiedGmailDraftRequest:
    task_id: str
    capability: str
    to: tuple[str, ...]
    subject: str
    body: str
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "capability": self.capability,
            "to": list(self.to),
            "cc": list(self.cc),
            "bcc": list(self.bcc),
            "subject": self.subject,
            "body_sha256": hashlib.sha256(
                self.body.encode("utf-8")
            ).hexdigest(),
        }

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()


VerifiedApprovalRequest = (
    VerifiedEditRequest
    | VerifiedEditBatchRequest
    | VerifiedFileWriteRequest
    | VerifiedGmailDraftRequest
)


def approval_action_for_request(
    request: VerifiedApprovalRequest,
) -> str:
    if isinstance(request, VerifiedEditBatchRequest):
        action_type = "verified_edit_batch"
    elif isinstance(request, VerifiedFileWriteRequest):
        action_type = "verified_file_write"
    elif isinstance(request, VerifiedGmailDraftRequest):
        action_type = "verified_gmail_draft"
    else:
        action_type = "verified_edit"

    return json.dumps(
        {
            "type": action_type,
            "fingerprint": request.fingerprint(),
            "request": request.canonical_payload(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def validate_stored_approval(
    approval_row: dict[str, Any],
    request: VerifiedApprovalRequest,
) -> ApprovalRecord:
    if not approval_row:
        raise PermissionError("Approval record was not found.")

    if approval_row.get("status") != "approved":
        raise PermissionError("Approval is not approved.")

    if approval_row.get("task_id") != request.task_id:
        raise PermissionError(
            "Approval belongs to a different task."
        )

    expected_action = approval_action_for_request(request)

    if approval_row.get("action") != expected_action:
        raise PermissionError(
            "Approval does not match the exact verified request."
        )

    decided_at = approval_row.get("decided_at")
    decided_by = approval_row.get("decided_by")

    if not decided_at:
        raise PermissionError(
            "Approval decision timestamp is missing."
        )

    if not decided_by:
        raise PermissionError(
            "Approval decision actor is missing."
        )

    return ApprovalRecord(
        approval_id=str(approval_row["id"]),
        task_id=request.task_id,
        capability=request.capability,
        status="approved",
        decided_at=str(decided_at),
        decided_by=str(decided_by),
        consumed=False,
    )