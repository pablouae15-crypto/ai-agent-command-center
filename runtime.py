from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone

from agent import run_orchestrator
from config import Settings
from store import TaskStore


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
                        output = await run_orchestrator(task, self.settings.openai_model)
                        self.store.complete_task(task["id"], {"output": output, "completed_at": datetime.now(timezone.utc).isoformat()})
                    except Exception as exc:  # noqa: BLE001 - the task must be audited as failed.
                        self.store.fail_task(task["id"], str(exc))
            await asyncio.sleep(self.settings.worker_poll_seconds)
