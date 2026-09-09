from pathlib import Path


def test_dashboard_contains_structured_approval_controls() -> None:
    html = Path(
        r"D:\AI-Agent-Command-Center\static\index.html"
    ).read_text(encoding="utf-8")

    assert "Approval: ${esc(a.id)}" in html
    assert "Task: ${esc(a.task_id || '—')}" in html
    assert "Status: ${esc(a.status || 'pending')}" in html
    assert "decide('${a.id}','approved')" in html
    assert "decide('${a.id}','rejected')" in html


def test_dashboard_escapes_dynamic_approval_text() -> None:
    html = Path(
        r"D:\AI-Agent-Command-Center\static\index.html"
    ).read_text(encoding="utf-8")

    assert "${esc(a.action)}" in html
    assert "${esc(a.reason)}" in html
    assert "${esc(a.id)}" in html
    assert "${esc(a.task_id || '—')}" in html
    assert "${esc(a.status || 'pending')}" in html


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
