from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from engine.approvals import ApprovalRecord


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


def approval_action_for_request(
    request: VerifiedEditRequest,
) -> str:
    return json.dumps(
        {
            "type": "verified_edit",
            "fingerprint": request.fingerprint(),
            "request": request.canonical_payload(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def validate_stored_approval(
    approval_row: dict[str, Any],
    request: VerifiedEditRequest,
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
            "Approval does not match the exact verified edit request."
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