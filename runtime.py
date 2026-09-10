from __future__ import annotations

import asyncio
import contextlib
import json
import re
from datetime import datetime, timezone

from agent import SpecialistOutcome
from agent import run_specialist
from agent import execute_approved_gmail_draft
from agent import execute_approved_verified_edit
from config import Settings
from store import TaskStore
from write_approval import VerifiedEditRequest


def _verified_edit_request_from_task(
    task: dict,
    metadata: dict,
) -> VerifiedEditRequest | None:
    text = str(
        metadata.get("original_request")
        or task.get("description")
        or ""
    ).strip()

    sandbox_root = r"D:\Shared-Local-Execution-Engine-Sandbox"

    legacy_pattern = re.compile(
        r'In\s+(?P<path>[A-Za-z]:\\[^,\r\n]+),\s*'
        r'replace exactly\s+"(?P<old>.*?)"\s+with\s+"(?P<new>.*?)"\.\s*'
        r'Use the approved verified replace_text workflow with repository path\s+'
        r'(?P<repo>[A-Za-z]:\\.+?)\s+and sandbox_pytest verification\.',
        re.IGNORECASE | re.DOTALL,
    )

    dashboard_pattern = re.compile(
        r'Use\s+verified\s+replace\s+text\s+to\s+update\s+'
        r'(?P<path>[A-Za-z]:\\[^\r\n]+?)\.\s*'
        r'Replace\s+exactly\s+this\s+text:\s*'
        r'(?P<old>.*?)\s*'
        r'With\s+exactly\s+this\s+text:\s*'
        r'(?P<new>.*?)\s*'
        r'Do\s+not\s+modify\s+any\s+other\s+file\.',
        re.IGNORECASE | re.DOTALL,
    )

    match = legacy_pattern.search(text)
    repository_path = sandbox_root

    if match:
        repository_path = match.group("repo").strip()
    else:
        match = dashboard_pattern.search(text)

    if not match:
        return None

    file_path = match.group("path").strip()
    old_text = match.group("old").strip()
    new_text = match.group("new").strip()

    if not file_path.lower().startswith(sandbox_root.lower() + "\\"):
        return None

    if repository_path.lower() != sandbox_root.lower():
        return None

    return VerifiedEditRequest(
        task_id=str(task["id"]),
        capability="replace_text",
        path=file_path,
        repository_path=repository_path,
        verification_profile="sandbox_pytest",
        old_text=old_text,
        new_text=new_text,
        expected_replacements=1,
    )


def _specialist_output_indicates_failure(output: str) -> bool:
    """Detect explicit specialist refusal/no-action outcomes."""
    normalized = output.lower().replace("’", "'")

    failure_markers = (
        "i can't perform",
        "i cannot perform",
        "can't perform",
        "cannot perform",
        "unable to perform",
        "unable to execute",
        "can't execute",
        "cannot execute",
        "required authorization is unavailable",
        "approval_id was not provided",
        "approval id was not provided",
    )

    no_action_markers = (
        "no changes were made",
        "no action was taken",
        "nothing was changed",
        "nothing was executed",
        "did not execute",
        "did not perform",
        "verification did not run",
        "no verification ran",
        "no files were inspected or changed",
        "was not run",
    )

    insufficient_evidence_markers = (
        "no repository evidence",
        "no evidence has been provided",
        "evidence has not been provided",
        "context has not been provided",
        "required context is unavailable",
        "i can't reliably",
        "i cannot reliably",
        "can't reliably summarize",
        "cannot reliably summarize",
        "need the authorized sandbox path",
        "need the task id",
    )

    explicit_refusal = (
        any(marker in normalized for marker in failure_markers)
        and any(marker in normalized for marker in no_action_markers)
    )

    insufficient_evidence = (
        any(marker in normalized for marker in insufficient_evidence_markers)
        and (
            "can't reliably" in normalized
            or "cannot reliably" in normalized
            or "need the " in normalized
        )
    )

    return explicit_refusal or insufficient_evidence


class Runtime:
    def __init__(self, store: TaskStore, settings: Settings):
        self.store = store
        self.settings = settings
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._stop.clear()
        self._tasks = [
            asyncio.create_task(self._scheduler_loop(), name="scheduler"),
            asyncio.create_task(self._worker_loop(), name="worker"),
        ]

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []

    async def _scheduler_loop(self) -> None:
        while not self._stop.is_set():
            for job in self.store.due_jobs():
                task = self.store.create_task(
                    title=f"Recurring: {job['name']}",
                    description=job["prompt"],
                    agent_name=job["agent_name"],
                    priority="Low",
                    source=f"schedule:{job['name']}",
                )
                self.store.advance_job(job["id"], job["interval_seconds"])
                self.store.add_activity("schedule.enqueued", f"Recurring job enqueued: {job['name']}", task_id=task["id"],
                                        agent_name=job["agent_name"], payload={"job_id": job["id"]})
            await asyncio.sleep(self.settings.scheduler_poll_seconds)

    async def _worker_loop(self) -> None:
        while not self._stop.is_set():
            if self.settings.enable_agent_runs:
                task = self.store.claim_next_task()
                if task:
                    try:
                        metadata = json.loads(
                            task.get("metadata_json") or "{}"
                        )

                        if (
                            metadata.get("_defer_exact_approval")
                            and not task.get("approval_id")
                        ):
                            exact_request = _verified_edit_request_from_task(
                                task,
                                metadata,
                            )

                            if exact_request is not None:
                                self.store.create_exact_approval(
                                    exact_request,
                                    reason="Execute this exact verified edit",
                                )
                                continue

                        if (
                            metadata.get("workflow_type")
                            == "native_gmail_draft"
                        ):
                            approval_id = str(
                                task.get("approval_id") or ""
                            ).strip()

                            if not approval_id:
                                raise PermissionError(
                                    "Native Gmail draft task has no approval ID."
                                )

                            approval = self.store.get_approval(
                                approval_id
                            )

                            if not approval:
                                raise PermissionError(
                                    "Native Gmail draft approval was not found."
                                )

                            preview = json.loads(
                                approval.get(
                                    "display_payload_json"
                                )
                                or "{}"
                            )

                            if preview.get("type") != "gmail_draft":
                                raise PermissionError(
                                    "Approval does not contain a Gmail draft payload."
                                )

                            output = execute_approved_gmail_draft(
                                store=self.store,
                                task_id=str(task["id"]),
                                approval_id=approval_id,
                                to=list(preview.get("to") or []),
                                cc=list(preview.get("cc") or []),
                                bcc=list(preview.get("bcc") or []),
                                subject=str(
                                    preview.get("subject") or ""
                                ),
                                body=str(
                                    preview.get("body") or ""
                                ),
                            )
                        elif task.get("approval_id"):
                            approval_id = str(
                                task.get("approval_id") or ""
                            ).strip()

                            if not approval_id:
                                raise PermissionError(
                                    "Approved task has no approval ID."
                                )

                            approval = self.store.get_approval(
                                approval_id
                            )

                            if not approval:
                                raise PermissionError(
                                    "Approved task approval record was not found."
                                )

                            if approval.get("status") != "approved":
                                raise PermissionError(
                                    "Approval is not in approved state."
                                )

                            preview = json.loads(
                                approval.get(
                                    "display_payload_json"
                                )
                                or "{}"
                            )

                            if (
                                not preview
                                and approval.get("action") == task.get("title")
                            ):
                                exact_request = _verified_edit_request_from_task(
                                    task,
                                    metadata,
                                )

                                if exact_request is not None:
                                    self.store.create_exact_approval(
                                        exact_request,
                                        reason="Execute this exact verified edit",
                                    )
                                    continue

                            if preview.get("type") == "verified_edit_execution":
                                output = execute_approved_verified_edit(
                                    store=self.store,
                                    task_id=str(task["id"]),
                                    approval_id=approval_id,
                                    path=str(preview.get("path") or ""),
                                    repository_path=str(
                                        preview.get("repository_path") or ""
                                    ),
                                    old_text=str(
                                        preview.get("old_text") or ""
                                    ),
                                    new_text=str(
                                        preview.get("new_text") or ""
                                    ),
                                    expected_replacements=int(
                                        preview.get("expected_replacements", 1)
                                    ),
                                )
                            else:
                                output = await run_specialist(
                                    task,
                                    self.settings.openai_model,
                                    self.store,
                                )

                            normalized_output = str(output)

                            if (
                                "'status': 'rolled_back'" in normalized_output
                                or '"status": "rolled_back"' in normalized_output
                                or "'verified': False" in normalized_output
                                or '"verified": false' in normalized_output.lower()
                            ):
                                raise RuntimeError(
                                    "Verified edit execution failed verification: "
                                    f"{normalized_output}"
                                )

                        else:
                            output = await run_specialist(
                                task,
                                self.settings.openai_model,
                                self.store,
                            )

                        if isinstance(output, SpecialistOutcome):
                            persisted_output = output.model_dump()

                            if output.status == "completed":
                                self.store.complete_task(
                                    task["id"],
                                    {
                                        "output": persisted_output,
                                        "completed_at": datetime.now(
                                            timezone.utc
                                        ).isoformat(),
                                    },
                                )
                                continue

                            evidence_text = (
                                f" Evidence: {', '.join(output.evidence)}"
                                if output.evidence
                                else ""
                            )

                            if output.status == "failed":
                                self.store.fail_task(
                                    task["id"],
                                    f"{output.summary}{evidence_text}",
                                )
                                continue

                            if output.status == "blocked":
                                self.store.block_task(
                                    task["id"],
                                    output.summary,
                                )
                                continue

                            if output.status == "partial":
                                self.store.partial_task(
                                    task["id"],
                                    persisted_output,
                                    output.summary,
                                )
                                continue

                            raise RuntimeError(
                                f"Unsupported specialist outcome status: {output.status}"
                            )

                        normalized_output = str(output)

                        if _specialist_output_indicates_failure(
                            normalized_output
                        ):
                            raise RuntimeError(normalized_output)

                        self.store.complete_task(
                            task["id"],
                            {
                                "output": output,
                                "completed_at": datetime.now(
                                    timezone.utc
                                ).isoformat(),
                            },
                        )
                    except Exception as exc:  # noqa: BLE001 - the task must be audited as failed.
                        self.store.fail_task(task["id"], str(exc))
            await asyncio.sleep(self.settings.worker_poll_seconds)
