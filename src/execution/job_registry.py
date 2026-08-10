"""Generic background process execution independent of selection strategies."""

from __future__ import annotations

import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class JobRegistry:
    """Small in-memory registry for long-running application operations."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, command: list[str], label: str) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "label": label,
            "status": "RUNNING",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "output": "",
            "return_code": None,
        }
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(
            target=self._run, args=(job_id, command), daemon=True
        )
        thread.start()
        return dict(job)

    def _run(self, job_id: str, command: list[str]) -> None:
        try:
            result = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60 * 60,
                check=False,
            )
            output = (result.stdout + "\n" + result.stderr).strip()[-20_000:]
            status = "SUCCEEDED" if result.returncode == 0 else "FAILED"
            return_code = result.returncode
        except Exception as exc:  # pragma: no cover - defensive job boundary
            output = str(exc)
            status = "FAILED"
            return_code = -1
        with self._lock:
            self._jobs[job_id].update(
                {
                    "status": status,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "output": output,
                    "return_code": return_code,
                }
            )

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            values = [dict(job) for job in self._jobs.values()]
        return sorted(values, key=lambda item: item["started_at"], reverse=True)[:20]
