from __future__ import annotations

from pathlib import Path
import sys
from typing import Any


ENGINE_ROOT = Path(r"D:\Shared-Local-Execution-Engine")

if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from engine.approvals import ApprovalRecord
from engine.service import LocalExecutionEngine


class ExecutionEngineDisabledError(RuntimeError):
    pass


class ExecutionEngineAdapter:
    def __init__(
        self,
        *,
        enabled: bool,
        authorized_roots: list[str | Path],
        audit_log_path: str | Path,
    ):
        self.enabled = enabled
        self.authorized_roots = [Path(root) for root in authorized_roots]
        self.audit_log_path = Path(audit_log_path)

        self._engine = (
            LocalExecutionEngine(
                self.authorized_roots,
                audit_log_path=self.audit_log_path,
            )
            if self.enabled and self.authorized_roots
            else None
        )

    @property
    def ready(self) -> bool:
        return self.enabled and self._engine is not None

    def _require_ready(self) -> LocalExecutionEngine:
        if not self.ready:
            raise ExecutionEngineDisabledError(
                "Shared Local Execution Engine is disabled or has no authorized workspace."
            )

        return self._engine

    def list_directory(
        self,
        path: str | Path,
        *,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._require_ready().list_directory(
            path,
            task_id=task_id,
        )

    def read_text_file(
        self,
        path: str | Path,
        *,
        task_id: str | None = None,
        max_bytes: int = 1_000_000,
    ) -> dict[str, Any]:
        return self._require_ready().read_text_file(
            path,
            task_id=task_id,
            max_bytes=max_bytes,
        )

    def search_text(
        self,
        root: str | Path,
        query: str,
        *,
        task_id: str | None = None,
        max_results: int = 200,
    ) -> list[dict[str, Any]]:
        return self._require_ready().search_text(
            root,
            query,
            task_id=task_id,
            max_results=max_results,
        )

    def git_status(
        self,
        path: str | Path,
        *,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        return self._require_ready().git_status(
            path,
            task_id=task_id,
        )

    def git_diff(
        self,
        path: str | Path,
        *,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        return self._require_ready().git_diff(
            path,
            task_id=task_id,
        )

    def git_log(
        self,
        path: str | Path,
        *,
        task_id: str | None = None,
        max_count: int = 20,
    ) -> dict[str, Any]:
        return self._require_ready().git_log(
            path,
            task_id=task_id,
            max_count=max_count,
        )

    def run_command_profile(
        self,
        profile_id: str,
        cwd: str | Path,
        *,
        task_id: str | None = None,
        approval=None,
    ):
        return self._require_ready().run_command_profile(
            profile_id,
            cwd,
            task_id=task_id,
            approval=approval,
        )

    def verified_write_text_file(
        self,
        path: str | Path,
        content: str,
        *,
        repository_path: str | Path,
        verification_profile: str,
        task_id: str,
        approval: ApprovalRecord,
        expected_sha256: str | None = None,
        max_bytes: int = 1_000_000,
    ) -> dict[str, Any]:
        if not isinstance(approval, ApprovalRecord):
            raise TypeError(
                "verified_write_text_file requires a validated ApprovalRecord."
            )

        return self._require_ready().verified_write_text_file(
            path,
            content,
            repository_path=repository_path,
            verification_profile=verification_profile,
            task_id=task_id,
            approval=approval,
            expected_sha256=expected_sha256,
            max_bytes=max_bytes,
        )

    def verified_replace_text(
        self,
        path: str | Path,
        old_text: str,
        new_text: str,
        *,
        repository_path: str | Path,
        verification_profile: str,
        task_id: str,
        approval: ApprovalRecord,
        expected_replacements: int = 1,
        expected_sha256: str | None = None,
        max_bytes: int = 1_000_000,
    ) -> dict[str, Any]:
        if not isinstance(approval, ApprovalRecord):
            raise TypeError(
                "verified_replace_text requires a validated ApprovalRecord."
            )

        return self._require_ready().verified_replace_text(
            path,
            old_text,
            new_text,
            repository_path=repository_path,
            verification_profile=verification_profile,
            task_id=task_id,
            approval=approval,
            expected_replacements=expected_replacements,
            expected_sha256=expected_sha256,
            max_bytes=max_bytes,
        )