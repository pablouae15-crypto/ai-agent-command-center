from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import agent
import runtime as runtime_module
from runtime import Runtime
from store import TaskStore
from write_approval import VerifiedGmailDraftRequest


class FakeDraftCreate:
    def __init__(self, parent, *, user_id, body):
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
            "id": "runtime-draft-001",
            "message": {
                "id": "runtime-message-001",
            },
        }


class FakeDrafts:
    def __init__(self, parent):
        self.parent = parent

    def create(self, *, userId, body):
        return FakeDraftCreate(
            self.parent,
            user_id=userId,
            body=body,
        )


class FakeUsers:
    def __init__(self, parent):
        self.parent = parent

    def drafts(self):
        return FakeDrafts(self.parent)


class FakeGmailService:
    def __init__(self):
        self.calls = []

    def users(self):
        return FakeUsers(self)


def test_native_gmail_runtime_bypasses_llm_and_creates_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = TaskStore(
        db_path=tmp_path / "runtime.db",
        audit_log_path=tmp_path / "audit.jsonl",
    )

    store.seed_defaults()

    task = store.create_task(
        title="Native Gmail runtime test",
        description="Prepare approved Gmail draft.",
        agent_name="Email / Calendar",
        priority="Medium",
        side_effect_level="external",
        requires_approval=False,
        metadata={
            "workflow_type": "native_gmail_draft",
        },
    )

    request = VerifiedGmailDraftRequest(
        task_id=str(task["id"]),
        capability="gmail.draft.create",
        to=("recipient@example.com",),
        subject="Runtime Gmail Test",
        body="Runtime approved Gmail draft body.",
        cc=(),
        bcc=(),
    )

    pending = store.create_exact_approval(
        request,
        reason="Create this exact Gmail draft",
    )

    store.decide_approval(
        str(pending["id"]),
        "approved",
        decided_by="runtime-test-user",
    )

    fake_service = FakeGmailService()

    monkeypatch.setattr(
        agent,
        "build_gmail_draft_service",
        lambda: fake_service,
    )

    async def forbidden_run_specialist(*args, **kwargs):
        raise AssertionError(
            "LLM specialist must not run for native Gmail draft."
        )

    monkeypatch.setattr(
        runtime_module,
        "run_specialist",
        forbidden_run_specialist,
    )

    settings = SimpleNamespace(
        enable_agent_runs=True,
        worker_poll_seconds=0.01,
        scheduler_poll_seconds=3600,
        openai_model="unused",
    )

    runtime = Runtime(
        store,
        settings,
    )

    async def run_worker():
        worker = asyncio.create_task(
            runtime._worker_loop()
        )

        for _ in range(100):
            current = store.get_task(
                str(task["id"])
            )

            if current["status"] in {
                "completed",
                "failed",
            }:
                break

            await asyncio.sleep(0.01)

        runtime._stop.set()

        try:
            await asyncio.wait_for(
                worker,
                timeout=1,
            )
        except asyncio.CancelledError:
            pass

    asyncio.run(run_worker())

    completed = store.get_task(
        str(task["id"])
    )

    assert completed is not None
    assert completed["status"] == "completed"

    assert len(fake_service.calls) == 1

    execution = store.get_gmail_draft_execution(
        str(pending["id"])
    )

    assert execution is not None
    assert execution["status"] == "created"
    assert (
        execution["gmail_draft_id"]
        == "runtime-draft-001"
    )
    assert (
        execution["gmail_message_id"]
        == "runtime-message-001"
    )
