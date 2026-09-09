from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agents.tool_context import ToolContext

from agent import build_verified_replace_text_tool
from store import TaskStore
from write_approval import VerifiedEditRequest


SANDBOX = Path(r"D:\Shared-Local-Execution-Engine-Sandbox")
APP_PATH = SANDBOX / "app.py"
REPOSITORY_PATH = str(SANDBOX)


def invoke_tool(tool, payload: dict[str, object]) -> str:
    serialized = json.dumps(payload)

    context = ToolContext(
        context=None,
        tool_name="verified_replace_text",
        tool_call_id="integration-tool-call",
        tool_arguments=serialized,
    )

    async def run() -> str:
        return await tool.on_invoke_tool(context, serialized)

    return asyncio.run(run())


def create_approved_request(
    store: TaskStore,
    task_id: str,
    *,
    old_text: str,
    new_text: str,
) -> dict[str, object]:
    request = VerifiedEditRequest(
        task_id=task_id,
        capability="replace_text",
        path=str(APP_PATH),
        repository_path=REPOSITORY_PATH,
        verification_profile="sandbox_pytest",
        old_text=old_text,
        new_text=new_text,
        expected_replacements=1,
    )

    pending = store.create_exact_approval(request)

    return store.decide_approval(
        str(pending["id"]),
        "approved",
        decided_by="integration-test",
    )


def payload(
    approval_id: str,
    *,
    old_text: str,
    new_text: str,
) -> dict[str, object]:
    return {
        "approval_id": approval_id,
        "path": str(APP_PATH),
        "repository_path": REPOSITORY_PATH,
        "old_text": old_text,
        "new_text": new_text,
        "expected_replacements": 1,
    }


def test_real_verified_replace_success_restore_and_rollback(
    tmp_path: Path,
) -> None:
    original = APP_PATH.read_text(encoding="utf-8")

    assert "return a + b" in original
    assert "return a - b" not in original

    store = TaskStore(
        db_path=tmp_path / "command-center.db",
        audit_log_path=tmp_path / "command-center-audit.jsonl",
    )

    task = store.create_task(
        title="Real verified edit integration test",
        description="Exercise approval, FunctionTool, adapter, engine, pytest, and rollback.",
        agent_name="Orchestrator",
        requires_approval=False,
    )

    task_id = str(task["id"])
    tool = build_verified_replace_text_tool(store, task_id)

    good_approval = create_approved_request(
        store,
        task_id,
        old_text="return a + b",
        new_text="return (a + b)",
    )

    good_result = invoke_tool(
        tool,
        payload(
            str(good_approval["id"]),
            old_text="return a + b",
            new_text="return (a + b)",
        ),
    )

    assert "'status': 'verified'" in good_result
    assert "'verified': True" in good_result
    assert "return (a + b)" in APP_PATH.read_text(encoding="utf-8")

    restore_approval = create_approved_request(
        store,
        task_id,
        old_text="return (a + b)",
        new_text="return a + b",
    )

    restore_result = invoke_tool(
        tool,
        payload(
            str(restore_approval["id"]),
            old_text="return (a + b)",
            new_text="return a + b",
        ),
    )

    assert "'status': 'verified'" in restore_result
    assert "'verified': True" in restore_result
    assert APP_PATH.read_text(encoding="utf-8") == original

    bad_approval = create_approved_request(
        store,
        task_id,
        old_text="return a + b",
        new_text="return a - b",
    )

    bad_result = invoke_tool(
        tool,
        payload(
            str(bad_approval["id"]),
            old_text="return a + b",
            new_text="return a - b",
        ),
    )

    assert "'status': 'rolled_back'" in bad_result
    assert "'verified': False" in bad_result
    assert "'restored': True" in bad_result

    final_text = APP_PATH.read_text(encoding="utf-8")

    assert final_text == original
    assert "return a + b" in final_text
    assert "return a - b" not in final_text
