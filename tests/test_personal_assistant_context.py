from pathlib import Path

MAIN_PATH = Path(r"D:\AI-Agent-Command-Center\main.py")
ASSISTANT_PATH = Path(r"D:\AI-Agent-Command-Center\personal_assistant.py")


def test_personal_assistant_handoff_includes_command_center_context() -> None:
    main_source = MAIN_PATH.read_text(encoding="utf-8")
    assistant_source = ASSISTANT_PATH.read_text(encoding="utf-8")

    assert "build_personal_assistant_context" in assistant_source
    assert "command_center_context" in assistant_source
    assert "original_request" in assistant_source
    assert "store.list_task_visibility" in assistant_source
    assert "store.list_agents" in assistant_source
    assert "store.list_approvals" in assistant_source
    assert "store.list_activity" in assistant_source
    assert "handoff_to_command_center(store, safe_request)" in main_source

def test_personal_assistant_context_compacts_task_payloads(tmp_path: Path) -> None:
    import json

    from personal_assistant import build_personal_assistant_context
    from store import TaskStore

    store = TaskStore(
        tmp_path / "command_center.db",
        tmp_path / "audit.jsonl",
    )

    task = store.create_task(
        title="Large historical task",
        description="X" * 20000,
        agent_name="Orchestrator",
        metadata={
            "large_context": "Y" * 20000,
        },
    )

    with store._connect() as db:
        db.execute(
            "UPDATE tasks SET result_json=? WHERE id=?",
            (
                json.dumps({"output": "Z" * 20000}),
                str(task["id"]),
            ),
        )

    context = build_personal_assistant_context(store)

    assert len(context["tasks"]) == 1

    compact_task = context["tasks"][0]

    assert compact_task["id"] == task["id"]
    assert compact_task["title"] == "Large historical task"

    assert "description" not in compact_task
    assert "result_json" not in compact_task
    assert "metadata_json" not in compact_task

    serialized = json.dumps(context, default=str)
    assert len(serialized) < 10000


def test_personal_assistant_context_compacts_repeated_records(
    tmp_path: Path,
) -> None:
    import json

    from personal_assistant import build_personal_assistant_context
    from store import TaskStore

    store = TaskStore(
        tmp_path / "compact-context.db",
        tmp_path / "compact-context.jsonl",
    )
    store.seed_defaults()

    task = store.create_task(
        title="Context compaction task",
        description="Keep this task visible.",
        agent_name="Orchestrator",
    )
    store.add_activity(
        "test.large_activity",
        "Recent activity",
        task_id=str(task["id"]),
        payload={"large": "X" * 20000},
    )

    context = build_personal_assistant_context(store)

    assert len(context["agents"]) == 12
    assert all(
        set(agent) == {"name", "status", "current_task_id"}
        for agent in context["agents"]
    )
    assert all("payload_json" not in activity for activity in context["activity"])
    assert all("display_payload_json" not in approval for approval in context["approvals"])
    assert len(json.dumps(context, default=str)) < 10000
