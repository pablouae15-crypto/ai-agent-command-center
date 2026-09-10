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
