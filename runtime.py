from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone

from agent import SpecialistOutcome
from agent import run_specialist
from config import Settings
from store import TaskStore


def _specialist_output_indicates_failure(output: str) -> bool:
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
