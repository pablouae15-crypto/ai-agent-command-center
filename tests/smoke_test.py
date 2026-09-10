from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def request(url: str, method: str = "GET", payload: dict | None = None) -> dict | list:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())


def main() -> int:
    port = "18421"
    with tempfile.TemporaryDirectory() as temp_dir:
        env = os.environ.copy()
        env["APP_PORT"] = port
        env["ENABLE_AGENT_RUNS"] = "false"
        env["PYTHON_DOTENV_DISABLED"] = "true"
        env.pop("OPENAI_API_KEY", None)
        env["DB_PATH"] = str(Path(temp_dir) / "smoke.db")
        env["AUDIT_LOG_PATH"] = str(Path(temp_dir) / "audit.jsonl")
        process = subprocess.Popen([sys.executable, "main.py"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(40):
                try:
                    health = request(f"{base}/health")
                    break
                except Exception:
                    time.sleep(0.25)
            else:
                print("smoke test failed: server did not start")
                return 1
            assert health["status"] == "ok"
            assert health["openai_key_configured"] is False
            created = request(f"{base}/api/tasks", "POST", {
                "title": "Smoke test task",
                "description": "Verify local task persistence and approval gates.",
                "priority": "High",
                "side_effect_level": "external",
            })
            assert created["status"] == "awaiting_approval"
            summary = request(f"{base}/api/summary")
            assert summary["approvals_waiting"] >= 1
            assert any(item["title"] == "Smoke test task" for item in summary["tasks"])
            approval = summary["approvals"][0]
            decided = request(f"{base}/api/approvals/{approval['id']}/approved", "POST")
            assert decided["status"] == "approved"
            after_decision = request(f"{base}/api/summary")
            smoke_task = next(item for item in after_decision["tasks"] if item["title"] == "Smoke test task")
            assert smoke_task["status"] == "queued"

            gmail = request(
                f"{base}/api/gmail/drafts/request",
                "POST",
                {
                    "to": ["recipient@example.com"],
                    "cc": ["cc@example.com"],
                    "bcc": [],
                    "subject": "Smoke Gmail Draft",
                    "body": "This is an approval-gated Gmail draft smoke test.",
                },
            )

            assert gmail["status"] == "awaiting_approval"
            assert gmail["task"]["agent_name"] == "Email / Calendar"
            assert gmail["approval"]["status"] == "pending"
            assert gmail["draft"]["to"] == ["recipient@example.com"]
            assert gmail["draft"]["cc"] == ["cc@example.com"]
            assert gmail["draft"]["subject"] == "Smoke Gmail Draft"
            assert gmail["draft"]["body"] == "This is an approval-gated Gmail draft smoke test."

            gmail_summary = request(f"{base}/api/summary")
            gmail_approval = next(
                item
                for item in gmail_summary["approvals"]
                if item["id"] == gmail["approval"]["id"]
            )

            preview = json.loads(
                gmail_approval["display_payload_json"]
            )

            assert preview == {
                "type": "gmail_draft",
                "to": ["recipient@example.com"],
                "cc": ["cc@example.com"],
                "bcc": [],
                "subject": "Smoke Gmail Draft",
                "body": "This is an approval-gated Gmail draft smoke test.",
            }

            print(
                "smoke test passed: health, persistence, approval gates, "
                "approval decision, and Gmail draft approval request"
            )
            return 0
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
