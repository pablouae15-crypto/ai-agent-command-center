from __future__ import annotations

import pytest

from agent import (
    _require_sandbox_path,
    authorized_workspace_root_for,
)
from runtime import _verified_edit_request_from_task


REPOSITORY_ROOT = r"D:\AI-Agent-Command-Center"
SANDBOX_ROOT = r"D:\Shared-Local-Execution-Engine-Sandbox"


def test_configured_roots_are_the_source_of_truth() -> None:
    assert authorized_workspace_root_for(
        rf"{REPOSITORY_ROOT}\agent.py"
    ).as_posix().lower() == REPOSITORY_ROOT.replace("\\", "/").lower()
    assert authorized_workspace_root_for(
        rf"{SANDBOX_ROOT}\app.py"
    ).as_posix().lower() == SANDBOX_ROOT.replace("\\", "/").lower()

    _require_sandbox_path(REPOSITORY_ROOT, repository=True)
    _require_sandbox_path(rf"{REPOSITORY_ROOT}\agent.py")


def test_unauthorized_workspace_is_rejected() -> None:
    with pytest.raises(PermissionError):
        authorized_workspace_root_for(
            r"D:\Not-A-Configured-Workspace\agent.py"
        )

    with pytest.raises(PermissionError):
        _require_sandbox_path(
            r"D:\Not-A-Configured-Workspace",
            repository=True,
        )


def test_verified_edit_parser_accepts_configured_repository_root() -> None:
    request_text = (
        rf'In {REPOSITORY_ROOT}\agent.py, replace exactly '
        '"old value" with "new value". '
        "Use the approved verified replace_text workflow with repository path "
        rf"{REPOSITORY_ROOT} and sandbox_pytest verification."
    )

    request = _verified_edit_request_from_task(
        {"id": "task-1", "description": request_text},
        {"original_request": request_text},
    )

    assert request is not None
    assert request.path == rf"{REPOSITORY_ROOT}\agent.py"
    assert request.repository_path == REPOSITORY_ROOT


def test_verified_edit_parser_rejects_unauthorized_repository_root() -> None:
    request_text = (
        r'In D:\Not-A-Configured-Workspace\agent.py, replace exactly '
        '"old value" with "new value". '
        "Use the approved verified replace_text workflow with repository path "
        r"D:\Not-A-Configured-Workspace and sandbox_pytest verification."
    )

    request = _verified_edit_request_from_task(
        {"id": "task-2", "description": request_text},
        {"original_request": request_text},
    )

    assert request is None
