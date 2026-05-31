from __future__ import annotations

import hmac
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4


ProgressCallback = Callable[[int, str, str], None]
JobWork = Callable[[ProgressCallback], dict[str, Any]]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class AnalysisJobManager:
    def __init__(self, *, max_workers: int = 4, ttl_seconds: int = 900):
        self.ttl_seconds = max(60, ttl_seconds)
        self._executor = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="analysis-job")
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, work: JobWork) -> dict[str, Any]:
        job_id = str(uuid4())
        token = secrets.token_urlsafe(24)
        now = utc_now()
        job = {
            "id": job_id,
            "token": token,
            "status": "queued",
            "progress": 1,
            "phase": "queued",
            "message": "Đã xếp tài liệu vào hàng xử lý.",
            "createdAt": now,
            "updatedAt": now,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._cleanup_locked()
            self._jobs[job_id] = job
        self._executor.submit(self._run, job_id, work)
        return {"jobId": job_id, "jobToken": token, "status": "queued", "progress": 1}

    def get(self, job_id: str, token: str) -> dict[str, Any] | None:
        with self._lock:
            self._cleanup_locked()
            job = self._jobs.get(job_id)
            if not job or not token or not hmac.compare_digest(str(job["token"]), token):
                return None
            return self._public_payload(job)

    def _run(self, job_id: str, work: JobWork) -> None:
        self._update(job_id, 3, "preparing", "Đang chuẩn bị tài liệu.", status="running")
        try:
            result = work(lambda progress, phase, message: self._update(job_id, progress, phase, message))
        except Exception as error:
            self._fail(job_id, str(error))
            return
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(
                {
                    "status": "completed",
                    "progress": 100,
                    "phase": "completed",
                    "message": "Đã hoàn tất báo cáo tương đồng.",
                    "updatedAt": utc_now(),
                    "result": result,
                }
            )

    def _update(
        self,
        job_id: str,
        progress: int,
        phase: str,
        message: str,
        *,
        status: str = "running",
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(
                {
                    "status": status,
                    "progress": max(int(job["progress"]), min(99, max(1, int(progress)))),
                    "phase": phase,
                    "message": message,
                    "updatedAt": utc_now(),
                }
            )

    def _fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(
                {
                    "status": "failed",
                    "phase": "failed",
                    "message": "Không thể hoàn tất báo cáo.",
                    "error": error,
                    "updatedAt": utc_now(),
                }
            )

    def _cleanup_locked(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(seconds=self.ttl_seconds)
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if datetime.fromisoformat(str(job["updatedAt"])) < cutoff
        ]
        for job_id in expired:
            self._jobs.pop(job_id, None)

    @staticmethod
    def _public_payload(job: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in job.items()
            if key in {"id", "status", "progress", "phase", "message", "createdAt", "updatedAt", "result", "error"}
            and value is not None
        }
