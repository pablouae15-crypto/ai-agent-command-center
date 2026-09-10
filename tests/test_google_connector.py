from pathlib import Path

import pytest

import google_connector


def test_google_connector_uses_readonly_scopes_only() -> None:
    scopes = set(google_connector.GOOGLE_READONLY_SCOPES)

    assert scopes == {
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
    }

    forbidden_fragments = {
        "gmail.modify",
        "gmail.send",
        "gmail.compose",
        "calendar.events",
        "calendar.app.created",
    }

    assert all(
        fragment not in scope
        for scope in scopes
        for fragment in forbidden_fragments
    )


def test_missing_client_secret_fails_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TestSettings:
        google_oauth_token_path = tmp_path / "missing-token.json"
        google_oauth_client_secret_path = tmp_path / "missing-client-secret.json"

    monkeypatch.setattr(
        google_connector,
        "settings",
        TestSettings(),
    )

    with pytest.raises(
        FileNotFoundError,
        match="Google OAuth client secret file is not configured",
    ):
        google_connector._load_credentials()


def test_gmail_builder_uses_readonly_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_credentials = object()
    calls = {}

    monkeypatch.setattr(
        google_connector,
        "_load_credentials",
        lambda: sentinel_credentials,
    )

    def fake_build(
        service_name,
        version,
        *,
        credentials,
        cache_discovery,
    ):
        calls["service_name"] = service_name
        calls["version"] = version
        calls["credentials"] = credentials
        calls["cache_discovery"] = cache_discovery
        return "gmail-service"

    monkeypatch.setattr(
        google_connector,
        "build",
        fake_build,
    )

    result = google_connector.build_gmail_readonly_service()

    assert result == "gmail-service"
    assert calls == {
        "service_name": "gmail",
        "version": "v1",
        "credentials": sentinel_credentials,
        "cache_discovery": False,
    }


def test_calendar_builder_uses_readonly_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_credentials = object()
    calls = {}

    monkeypatch.setattr(
        google_connector,
        "_load_credentials",
        lambda: sentinel_credentials,
    )

    def fake_build(
        service_name,
        version,
        *,
        credentials,
        cache_discovery,
    ):
        calls["service_name"] = service_name
        calls["version"] = version
        calls["credentials"] = credentials
        calls["cache_discovery"] = cache_discovery
        return "calendar-service"

    monkeypatch.setattr(
        google_connector,
        "build",
        fake_build,
    )

    result = google_connector.build_calendar_readonly_service()

    assert result == "calendar-service"
    assert calls == {
        "service_name": "calendar",
        "version": "v3",
        "credentials": sentinel_credentials,
        "cache_discovery": False,
    }



def test_gmail_draft_scope_is_isolated() -> None:
    draft_scopes = set(
        google_connector.GOOGLE_GMAIL_DRAFT_SCOPES
    )

    assert draft_scopes == {
        google_connector.settings.google_gmail_compose_scope,
    }

    assert all(
        "gmail.compose" not in scope
        for scope in google_connector.GOOGLE_READONLY_SCOPES
    )


def test_gmail_draft_builder_uses_draft_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_credentials = object()
    calls = {}

    monkeypatch.setattr(
        google_connector,
        "_load_gmail_draft_credentials",
        lambda: sentinel_credentials,
    )

    def fake_build(
        service_name,
        version,
        *,
        credentials,
        cache_discovery,
    ):
        calls["service_name"] = service_name
        calls["version"] = version
        calls["credentials"] = credentials
        calls["cache_discovery"] = cache_discovery
        return "gmail-draft-service"

    monkeypatch.setattr(
        google_connector,
        "build",
        fake_build,
    )

    result = google_connector.build_gmail_draft_service()

    assert result == "gmail-draft-service"
    assert calls == {
        "service_name": "gmail",
        "version": "v1",
        "credentials": sentinel_credentials,
        "cache_discovery": False,
    }


def test_no_gmail_send_helper_is_exposed() -> None:
    names = set(dir(google_connector))

    forbidden = {
        "send_gmail",
        "send_email",
        "gmail_send",
        "build_gmail_send_service",
    }

    assert names.isdisjoint(forbidden)
