from pathlib import Path


def test_dashboard_contains_structured_approval_controls() -> None:
    html = Path(
        r"D:\AI-Agent-Command-Center\static\index.html"
    ).read_text(encoding="utf-8")

    assert "approval.display_payload_json || '{}'" in html
    assert "Proposed change" in html
    assert "View technical details" in html
    assert "decide('${esc(approval.id)}','approved')" in html
    assert "decide('${esc(approval.id)}','rejected')" in html


def test_dashboard_escapes_dynamic_approval_text() -> None:
    html = Path(
        r"D:\AI-Agent-Command-Center\static\index.html"
    ).read_text(encoding="utf-8")

    assert "${esc(oldText)}" in html
    assert "${esc(newText)}" in html
    assert "${esc(approval.action || '')}" in html
    assert "${esc(approval.id)}" in html


def test_dashboard_confirms_approval_decisions() -> None:
    html = Path(
        r"D:\AI-Agent-Command-Center\static\index.html"
    ).read_text(encoding="utf-8")

    assert "window.confirm(" in html
    assert "APPROVE" in html
    assert "REJECT" in html
    assert "Approval ID: ${id}" in html


def test_dashboard_reports_approval_api_failures() -> None:
    html = Path(
        r"D:\AI-Agent-Command-Center\static\index.html"
    ).read_text(encoding="utf-8")

    assert "if (!response.ok)" in html
    assert "await response.json()" in html
    assert "window.alert(detail)" in html
    assert "encodeURIComponent(id)" in html

def test_dashboard_contains_archive_task_controls() -> None:
    html = Path(
        r"D:\AI-Agent-Command-Center\static\index.html"
    ).read_text(encoding="utf-8")

    assert "data-task-archive" in html
    assert "Archive this task from the active dashboard view?" in html
    assert "/api/tasks/${encodeURIComponent(taskId)}/archive" in html
    assert "Task archive failed" in html
