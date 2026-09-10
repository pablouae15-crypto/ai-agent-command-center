from pathlib import Path


MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"


def test_main_has_single_execution_status_route() -> None:
    source = MAIN_PATH.read_text(encoding="utf-8")
    assert source.count('@app.get("/api/execution/status")') == 1


def test_health_payload_does_not_duplicate_execution_engine_fields() -> None:
    source = MAIN_PATH.read_text(encoding="utf-8")

    health_section = source[
        source.index('@app.get("/health")'):
        source.index('@app.get("/api/execution/status")')
    ]

    assert health_section.count('"execution_engine_enabled"') == 1
    assert health_section.count('"execution_engine_ready"') == 1
    assert health_section.count('"authorized_workspace_count"') == 1


def test_summary_execution_note_is_not_stale_phase_one_text() -> None:
    source = MAIN_PATH.read_text(encoding="utf-8")

    summary_section = source[
        source.index('@app.get("/api/summary")'):
        source.index('@app.get("/api/tasks")')
    ]

    assert "external connectors are not enabled in Phase 1" not in summary_section


def test_main_has_single_execution_engine_import_and_instance() -> None:
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert source.count("from execution_adapter import ExecutionEngineAdapter") == 1
    assert source.count("execution_engine = ExecutionEngineAdapter(") == 1

