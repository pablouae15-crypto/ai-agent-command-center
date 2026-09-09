from __future__ import annotations

from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import settings


GOOGLE_READONLY_SCOPES = [
    settings.google_gmail_readonly_scope,
    settings.google_calendar_readonly_scope,
]


def _load_credentials() -> Credentials:
    token_path = Path(settings.google_oauth_token_path)
    client_secret_path = Path(settings.google_oauth_client_secret_path)

    credentials: Credentials | None = None

    if token_path.is_file():
        credentials = Credentials.from_authorized_user_file(
            str(token_path),
            GOOGLE_READONLY_SCOPES,
        )

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        if not client_secret_path.is_file():
            raise FileNotFoundError(
                "Google OAuth client secret file is not configured."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secret_path),
            GOOGLE_READONLY_SCOPES,
        )

        credentials = flow.run_local_server(port=0)

        token_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        token_path.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    return credentials


def build_gmail_readonly_service() -> Any:
    credentials = _load_credentials()

    return build(
        "gmail",
        "v1",
        credentials=credentials,
        cache_discovery=False,
    )


def build_calendar_readonly_service() -> Any:
    credentials = _load_credentials()

    return build(
        "calendar",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )
