from pathlib import Path


HTML_PATH = Path(
    r"D:\AI-Agent-Command-Center\static\index.html"
)


def test_task_operations_has_read_only_detail_modal() -> None:
    source = HTML_PATH.read_text(encoding="utf-8")

    assert 'id="task-detail-modal"' in source
    assert 'id="task-detail-content"' in source
    assert 'id="task-detail-close"' in source
    assert "openTaskDetail" in source
    assert "closeTaskDetail" in source
    assert "data-task-id" in source


def test_task_operations_defaults_to_newest_first() -> None:
    source = HTML_PATH.read_text(encoding="utf-8")

    assert "taskCreatedAt" in source
    assert "bCreated - aCreated" in source


def test_task_details_surfaces_status_result_before_full_context() -> None:
    source = HTML_PATH.read_text(encoding="utf-8")

    assert "function taskOutcomeDisplay(task)" in source
    assert "Task Result" in source
    assert "taskOutcomeDisplay(task)" in source
    assert "task.error || summary || 'No additional detail was provided.'" in source
    assert source.index("Task Result") < source.index("Full Description")
