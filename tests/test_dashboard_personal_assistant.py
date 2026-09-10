from pathlib import Path


HTML_PATH = Path(
    r"D:\AI-Agent-Command-Center\static\index.html"
)


def test_dashboard_exposes_personal_assistant_handoff() -> None:
    source = HTML_PATH.read_text(encoding="utf-8")

    assert "Personal AI Assistant" in source
    assert 'id="assistant-form"' in source
    assert 'id="assistant-request"' in source
    assert 'id="assistant-priority"' in source
    assert 'id="assistant-submit"' in source
    assert 'id="assistant-result"' in source

    assert "/api/assistant/handoff" in source
    assert "assistant-form" in source
