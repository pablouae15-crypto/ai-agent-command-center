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
