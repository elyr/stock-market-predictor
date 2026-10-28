"""
Background jobs.

Training models and running backtests take from seconds to minutes, so the API
starts them as jobs and returns immediately; the frontend polls the job until it
finishes. Each universe has its own lock, so a stock job and a crypto job can run
side by side while two jobs on the same universe run one after the other.
"""

import logging
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from api.store import now_iso

logger = logging.getLogger(__name__)


class Job:
    def __init__(self, kind: str, universe: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.universe = universe
        self.status = 'queued'
        self.message = 'Waiting to start'
        self.created_at = now_iso()
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.result: Any = None
        self.error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in ('id', 'kind', 'universe', 'status', 'message', 'created_at',
                                              'started_at', 'finished_at', 'result', 'error')}


class JobManager:
    def __init__(self, max_workers: int = 2):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='job')
        self._jobs: Dict[str, Job] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def lock(self, universe: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(universe, threading.Lock())

    def active(self, kind: str, universe: str) -> Optional[Job]:
        """A queued or running job of this kind for this universe, if any."""
        for job in self._jobs.values():
            if job.kind == kind and job.universe == universe and job.status in ('queued', 'running'):
                return job
        return None

    def submit(self, kind: str, universe: str, func: Callable[[Job], Any], dedupe: bool = True) -> Job:
        """
        Run ``func(job)`` in the background under the universe's lock.

        With ``dedupe``, an existing queued/running job of the same kind and
        universe is returned instead of starting another.
        """
        with self._guard:
            existing = self.active(kind, universe) if dedupe else None
            if existing:
                return existing
            job = Job(kind, universe)
            self._jobs[job.id] = job

        def run():
            with self.lock(universe):
                job.status, job.started_at, job.message = 'running', now_iso(), 'Running'
                try:
                    job.result = func(job)
                    job.status, job.message = 'succeeded', 'Done'
                except Exception as e:  # reported to the client through the job
                    logger.error(f"Job {job.kind}/{job.universe} failed: {e}\n{traceback.format_exc()}")
                    job.status, job.error, job.message = 'failed', str(e), 'Failed'
                finally:
                    job.finished_at = now_iso()

        self._executor.submit(run)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list(self, universe: Optional[str] = None) -> List[Job]:
        jobs = [j for j in self._jobs.values() if universe is None or j.universe == universe]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
