from __future__ import annotations

import asyncio
import base64
import json
from email import message_from_bytes
from pathlib import Path

import pytest
from agents.tool_context import ToolContext

import agent
from agent import build_gmail_create_draft_tool
from store import TaskStore
from write_approval import VerifiedGmailDraftRequest


def make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(
        db_path=tmp_path / "command-center.db",
        audit_log_path=tmp_path / "audit.jsonl",
    )


def make_task(store: TaskStore) -> dict[str, object]:
    return store.create_task(
        title="Approved Gmail draft",
        description="Test exact approval-gated Gmail draft creation.",
        agent_name="Email / Calendar",
        requires_approval=False,
    )


def make_request(
    task_id: str,
    *,
    to: tuple[str, ...] = ("recipient@example.com",),
    subject: str = "Approved subject",
    body: str = "Approved body",
    cc: tuple[str, ...] = (),
    bcc: tuple[str, ...] = (),
) -> VerifiedGmailDraftRequest:
    return VerifiedGmailDraftRequest(
        task_id=task_id,
        capability="gmail.draft.create",
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
    )


def approve(
    store: TaskStore,
    request: VerifiedGmailDraftRequest,
) -> dict[str, object]:
    pending = store.create_exact_approval(request)

    return store.decide_approval(
        str(pending["id"]),
        "approved",
        decided_by="test-user",
    )


def invoke_tool(
    tool,
    payload: dict[str, object],
) -> str:
    serialized = json.dumps(payload)

    context = ToolContext(
        context=None,
        tool_name="gmail_create_draft",
        tool_call_id="test-gmail-draft",
        tool_arguments=serialized,
    )

    async def run() -> str:
        return await tool.on_invoke_tool(
            context,
            serialized,
        )

    return asyncio.run(run())


class FakeDraftCreate:
    def __init__(
        self,
        parent,
        *,
        user_id,
        body,
    ) -> None:
        self.parent = parent
        self.user_id = user_id
        self.body = body

    def execute(self):
        self.parent.calls.append(
            {
                "userId": self.user_id,
                "body": self.body,
            }
        )

        return {
            "id": "draft-001",
            "message": {
                "id": "message-001",
            },
        }


class FakeDrafts:
    def __init__(self, parent) -> None:
        self.parent = parent

    def create(
        self,
        *,
        userId,
        body,
    ):
        return FakeDraftCreate(
            self.parent,
            user_id=userId,
            body=body,
        )


class FakeUsers:
    def __init__(self, parent) -> None:
        self.parent = parent

    def drafts(self):
        return FakeDrafts(self.parent)


class FakeGmailService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def users(self):
        return FakeUsers(self)


def test_exact_approved_gmail_draft_is_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)

    request = make_request(
        str(task["id"]),
        cc=("cc@example.com",),
    )

    approval = approve(
        store,
        request,
    )

    fake_service = FakeGmailService()

    monkeypatch.setattr(
        agent,
        "build_gmail_draft_service",
        lambda: fake_service,
    )

    tool = build_gmail_create_draft_tool(
        store,
        str(task["id"]),
    )

    result = invoke_tool(
        tool,
        {
            "approval_id": str(approval["id"]),
            "to": list(request.to),
            "subject": request.subject,
            "body": request.body,
            "cc": list(request.cc),
            "bcc": list(request.bcc),
        },
    )

    assert "draft_created" in result
    assert "draft-001" in result
    assert len(fake_service.calls) == 1

    call = fake_service.calls[0]

    assert call["userId"] == "me"

    raw = call["body"]["message"]["raw"]

    decoded = base64.urlsafe_b64decode(
        raw.encode("ascii")
    )

    message = message_from_bytes(decoded)

    assert message["To"] == "recipient@example.com"
    assert message["Cc"] == "cc@example.com"
    assert message["Subject"] == "Approved subject"

    payload = message.get_payload(decode=True).decode(
        message.get_content_charset() or "utf-8"
    )

    assert "Approved body" in payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("to", ["other@example.com"]),
        ("subject", "Changed subject"),
        ("body", "Changed body"),
        ("cc", ["changed-cc@example.com"]),
        ("bcc", ["changed-bcc@example.com"]),
    ],
)
def test_modified_draft_is_blocked_before_gmail_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)

    request = make_request(
        str(task["id"]),
    )

    approval = approve(
        store,
        request,
    )

    fake_service = FakeGmailService()

    monkeypatch.setattr(
        agent,
        "build_gmail_draft_service",
        lambda: fake_service,
    )

    tool = build_gmail_create_draft_tool(
        store,
        str(task["id"]),
    )

    payload = {
        "approval_id": str(approval["id"]),
        "to": list(request.to),
        "subject": request.subject,
        "body": request.body,
        "cc": list(request.cc),
        "bcc": list(request.bcc),
    }

    payload[field] = value

    result = invoke_tool(
        tool,
        payload,
    )

    assert "does not match the exact verified request" in result
    assert fake_service.calls == []


def test_missing_approval_id_blocks_gmail_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)

    fake_service = FakeGmailService()

    monkeypatch.setattr(
        agent,
        "build_gmail_draft_service",
        lambda: fake_service,
    )

    tool = build_gmail_create_draft_tool(
        store,
        str(task["id"]),
    )

    result = invoke_tool(
        tool,
        {
            "approval_id": "",
            "to": ["recipient@example.com"],
            "subject": "Subject",
            "body": "Body",
            "cc": [],
            "bcc": [],
        },
    )

    assert "approval_id is required" in result
    assert fake_service.calls == []


def test_unapproved_request_blocks_gmail_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)

    request = make_request(
        str(task["id"]),
    )

    pending = store.create_exact_approval(
        request
    )

    fake_service = FakeGmailService()

    monkeypatch.setattr(
        agent,
        "build_gmail_draft_service",
        lambda: fake_service,
    )

    tool = build_gmail_create_draft_tool(
        store,
        str(task["id"]),
    )

    result = invoke_tool(
        tool,
        {
            "approval_id": str(pending["id"]),
            "to": list(request.to),
            "subject": request.subject,
            "body": request.body,
            "cc": [],
            "bcc": [],
        },
    )

    assert "Approval is not approved" in result
    assert fake_service.calls == []


def test_same_approved_gmail_draft_is_not_created_twice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    approval = approve(store, request)

    fake_service = FakeGmailService()

    monkeypatch.setattr(
        agent,
        "build_gmail_draft_service",
        lambda: fake_service,
    )

    tool = build_gmail_create_draft_tool(
        store,
        str(task["id"]),
    )

    payload = {
        "approval_id": str(approval["id"]),
        "to": list(request.to),
        "subject": request.subject,
        "body": request.body,
        "cc": list(request.cc),
        "bcc": list(request.bcc),
    }

    first = invoke_tool(tool, payload)
    second = invoke_tool(tool, payload)

    assert "draft-001" in first
    assert "draft-001" in second

    assert len(fake_service.calls) == 1

    execution = store.get_gmail_draft_execution(
        str(approval["id"])
    )

    assert execution is not None
    assert execution["status"] == "created"
    assert execution["gmail_draft_id"] == "draft-001"
    assert execution["gmail_message_id"] == "message-001"


def test_failed_gmail_draft_execution_blocks_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path)
    task = make_task(store)
    request = make_request(str(task["id"]))
    approval = approve(store, request)

    store.begin_gmail_draft_execution(
        str(approval["id"]),
        str(task["id"]),
    )

    store.fail_gmail_draft_execution(
        str(approval["id"]),
        "ambiguous external failure",
    )

    fake_service = FakeGmailService()

    monkeypatch.setattr(
        agent,
        "build_gmail_draft_service",
        lambda: fake_service,
    )

    tool = build_gmail_create_draft_tool(
        store,
        str(task["id"]),
    )

    result = invoke_tool(
        tool,
        {
            "approval_id": str(approval["id"]),
            "to": list(request.to),
            "subject": request.subject,
            "body": request.body,
            "cc": list(request.cc),
            "bcc": list(request.bcc),
        },
    )

    assert "Automatic retry is blocked" in result
    assert fake_service.calls == []
