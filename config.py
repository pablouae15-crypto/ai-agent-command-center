from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _workspace_roots(value: str | None) -> list[str]:
    if not value:
        return []

    return [
        item.strip()
        for item in value.split(";")
        if item.strip()
    ]


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("APP_PORT", os.getenv("PORT", "8421")))

    db_path: Path = Path(
        os.getenv(
            "DB_PATH",
            str(BASE_DIR / "data" / "command_center.db"),
        )
    )

    audit_log_path: Path = Path(
        os.getenv(
            "AUDIT_LOG_PATH",
            str(BASE_DIR / "logs" / "audit.jsonl"),
        )
    )

    enable_agent_runs: bool = _as_bool(
        os.getenv("ENABLE_AGENT_RUNS"),
        False,
    )

    openai_model: str = os.getenv(
        "OPENAI_MODEL",
        "gpt-5",
    )

    scheduler_poll_seconds: float = float(
        os.getenv("SCHEDULER_POLL_SECONDS", "2")
    )

    worker_poll_seconds: float = float(
        os.getenv("WORKER_POLL_SECONDS", "2")
    )

    execution_engine_enabled: bool = _as_bool(
        os.getenv("EXECUTION_ENGINE_ENABLED"),
        False,
    )

    execution_engine_workspace_roots: tuple[str, ...] = tuple(
        _workspace_roots(
            os.getenv("EXECUTION_ENGINE_WORKSPACE_ROOTS")
        )
    )

    execution_engine_audit_log: Path = Path(
        os.getenv(
            "EXECUTION_ENGINE_AUDIT_LOG",
            str(BASE_DIR / "logs" / "execution-engine.jsonl"),
        )
    )

    google_oauth_client_secret_path: Path = Path(
        os.getenv(
            "GOOGLE_OAUTH_CLIENT_SECRET_PATH",
            str(BASE_DIR / "credentials" / "google_client_secret.json"),
        )
    )

    google_oauth_token_path: Path = Path(
        os.getenv(
            "GOOGLE_OAUTH_TOKEN_PATH",
            str(BASE_DIR / "credentials" / "google_token.json"),
        )
    )

    google_gmail_readonly_scope: str = (
        'https://www.googleapis.com/auth/gmail.readonly'
    )

    google_calendar_readonly_scope: str = (
        'https://www.googleapis.com/auth/calendar.readonly'
    )


    google_gmail_compose_scope: str = (
        'https://www.googleapis.com/auth/gmail.compose'
    )

    google_gmail_draft_token_path: Path = Path(
        os.getenv(
            "GOOGLE_GMAIL_DRAFT_TOKEN_PATH",
            str(
                BASE_DIR
                / "credentials"
                / "google_gmail_draft_token.json"
            ),
        )
    )


settings = Settings()

