from pathlib import Path


HTML_PATH = Path(
    r"D:\AI-Agent-Command-Center\static\index.html"
)


def test_dashboard_filters_use_persistent_browser_state() -> None:
    source = HTML_PATH.read_text(encoding="utf-8")

    assert "localStorage" in source

    assert "task-priority-filter" in source
    assert "task-owner-filter" in source
    assert "task-status-filter" in source

    assert "agent-search-filter" in source
    assert "agent-status-filter" in source

    assert "activity-sort-filter" in source

    assert "dashboard.task.priority" in source
    assert "dashboard.task.owner" in source
    assert "dashboard.task.status" in source

    assert "dashboard.agent.search" in source
    assert "dashboard.agent.status" in source

    assert "dashboard.activity.sort" in source
