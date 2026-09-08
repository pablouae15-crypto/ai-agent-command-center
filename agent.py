from __future__ import annotations

import os
from typing import Any

from agents import Agent, Runner


def api_key_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def build_orchestrator(model: str) -> Agent:
    return Agent(
        name="Command Center Orchestrator",
        model=model,
        instructions=(
            "You are the local AI Command Center orchestrator. Plan and summarize work clearly. "
            "You may reason about local task state, but you do not send email, modify calendars, "
            "delete files, submit applications, or perform any external write. When a request would "
            "have an external or destructive side effect, return a proposed action and state that "
            "human approval and a configured connector are required. Keep outputs concise and structured."
        ),
    )


async def run_orchestrator(task: dict[str, Any], model: str) -> str:
    if not api_key_configured():
        raise RuntimeError("OPENAI_API_KEY is not configured")
    result = await Runner.run(build_orchestrator(model), task["description"])
    output = getattr(result, "final_output", None)
    return str(output if output is not None else result)
