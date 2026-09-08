from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path_env(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("APP_HOST", "127.0.0.1")
    port: int = int(os.getenv("APP_PORT", "8421"))
    db_path: Path = _path_env("DB_PATH", "data/command_center.db")
    audit_log_path: Path = _path_env("AUDIT_LOG_PATH", "logs/audit.jsonl")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.6")
    enable_agent_runs: bool = _bool_env("ENABLE_AGENT_RUNS", False)
    scheduler_poll_seconds: float = float(os.getenv("SCHEDULER_POLL_SECONDS", "5"))
    worker_poll_seconds: float = float(os.getenv("WORKER_POLL_SECONDS", "3"))


settings = Settings()
