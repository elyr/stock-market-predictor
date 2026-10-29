"""
Background jobs.

Training models and running backtests take from seconds to minutes, so the API
starts them as jobs and returns immediately; the web app polls the job until it
finishes. Every job is a row in the database (kind, universe, parameters,
status, progress message, result), so any server process can report on it.

Two ways to run them (``JOB_QUEUE``):

- ``inline`` (default): a thread pool inside the server. Simple, one process.
- ``redis``: the server puts the job on a Redis queue (RQ) and separate worker
  processes run it (``python -m api.worker``). The server stays responsive
  during training, and several server copies can share the work.

Either way, the jobs of one universe run one after the other (a lock per
universe: a thread lock inline, a Redis lock with workers), while a stock job
and a crypto job can run side by side. A unique index stops two copies of the
same kind of job for the same universe from being queued at once.
"""

import json
import logging
import os
import socket
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional

from api.serialization import to_jsonable
from api.store import Store, now_iso
from api.tasks import TASKS, TIMEOUTS

logger = logging.getLogger(__name__)

QUEUE_NAME = 'ledger'
ACTIVE = ('queued', 'running')


class Job:
    """One job, as stored. Tasks report progress by setting ``job.message``."""

    def __init__(self, store: Store, row: Dict[str, Any]):
        self._store = store
        self.id = row['id']
        self.kind = row['kind']
        self.universe = row['universe']
        self.status = row['status']
        self._message = row['message']
        self.params = json.loads(row['params_json'] or '{}')
        self.created_at = row['created_at']
        self.started_at = row.get('started_at')
        self.finished_at = row.get('finished_at')
        self.result = json.loads(row['result_json']) if row.get('result_json') else None
        self.error = row.get('error')
        self.worker = row.get('worker')

    @property
    def message(self) -> str:
        return self._message

    @message.setter
    def message(self, value: str) -> None:
        if value != self._message:
            self._message = value
            self._store.update_job(self.id, message=value)

    def to_dict(self) -> Dict[str, Any]:
        return {'id': self.id, 'kind': self.kind, 'universe': self.universe, 'status': self.status,
                'message': self._message, 'created_at': self.created_at, 'started_at': self.started_at,
                'finished_at': self.finished_at, 'result': self.result, 'error': self.error, 'worker': self.worker}


def worker_name() -> str:
    return f'{socket.gethostname()}:{os.getpid()}'


class Runner:
    """
    Runs stored jobs: takes the universe's lock, calls the task, records the
    outcome. Used by the server's thread pool and by the worker processes.
    """

    def __init__(self, store: Store, services: Callable[[str], Any], lock: Callable[[str], Any],
                 metrics=None):
        self.store = store
        self.services = services
        self.lock = lock
        self.metrics = metrics
        self.functions: Dict[str, Callable] = {}  # job id -> function, for inline jobs submitted as callables

    def execute(self, job_id: str) -> None:
        row = self.store.get_job(job_id)
        if row is None:
            logger.error(f'Job {job_id} not found')
            return
        if row['status'] != 'queued':
            logger.warning(f"Job {job_id} is {row['status']}, not queued; skipped")
            return
        job = Job(self.store, row)
        kind, universe = job.kind, job.universe
        with self.lock(universe):
            started = time.monotonic()
            job.status, job.started_at = 'running', now_iso()
            job._message = 'Running'
            self.store.update_job(job.id, status='running', started_at=job.started_at, message='Running',
                                  worker=worker_name())
            if self.metrics:
                self.metrics.job_started(kind, universe)
            log = {'job_id': job.id, 'job_kind': kind, 'universe': universe}
            logger.info(f'Job {kind}/{universe} started', extra=log)
            try:
                function = self.functions.pop(job.id, None)
                if function is not None:
                    result = function(job)
                else:
                    result = TASKS[kind](self.services(universe), job, **job.params)
                job.status, job.result = 'succeeded', to_jsonable(result)
                self.store.update_job(job.id, status='succeeded', message='Done', finished_at=now_iso(),
                                      result_json=json.dumps(job.result))
            except Exception as e:  # reported to the client through the job
                logger.error(f'Job {kind}/{universe} failed: {e}\n{traceback.format_exc()}', extra=log)
                job.status, job.error = 'failed', str(e)
                self.store.update_job(job.id, status='failed', message='Failed', error=str(e),
                                      finished_at=now_iso())
            finally:
                seconds = time.monotonic() - started
                if self.metrics:
                    self.metrics.job_finished(kind, universe, job.status, seconds)
                if job.status == 'succeeded':
                    logger.info(f'Job {kind}/{universe} succeeded in {seconds:.1f}s',
                                extra={**log, 'duration_seconds': round(seconds, 3)})


class JobManager:
    """Creates jobs and hands them to the thread pool or the Redis queue."""

    def __init__(self, store: Store, services: Optional[Callable[[str], Any]] = None, metrics=None,
                 backend: str = 'inline', redis_url: Optional[str] = None, max_workers: int = 2, redis=None):
        if backend not in ('inline', 'redis'):
            raise ValueError(f"JOB_QUEUE must be 'inline' or 'redis', got {backend!r}")
        self.store = store
        self.metrics = metrics
        self.backend = backend
        self._locks: Dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._queue = None
        if backend == 'inline':
            self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='job')
            self.runner = Runner(store, services or (lambda u: None), self.lock, metrics)
            self._recover_interrupted()
        else:
            from redis import Redis
            from rq import Queue

            if redis is None and not redis_url:
                raise ValueError('JOB_QUEUE=redis needs REDIS_URL')
            self.redis = redis if redis is not None else Redis.from_url(redis_url)
            self._queue = Queue(QUEUE_NAME, connection=self.redis)
            self.runner = None

    # ---------------------------------------------------------------- locks

    def lock(self, universe: str) -> threading.Lock:
        """This process's lock for a universe (jobs inline, and requests that touch the pipeline)."""
        with self._guard:
            return self._locks.setdefault(universe, threading.Lock())

    # --------------------------------------------------------------- submit

    def submit(self, kind: str, universe: str, params: Optional[Dict[str, Any]] = None, dedupe: bool = True,
               func: Optional[Callable[[Job], Any]] = None) -> Job:
        """
        Queue a job and return it. With ``dedupe``, an existing queued or
        running job of the same kind and universe is returned instead.

        ``func`` runs a function instead of a named task (inline only; tests).
        """
        if func is None and kind not in TASKS:
            raise ValueError(f'Unknown job kind {kind!r}')
        if func is not None and self.backend != 'inline':
            raise ValueError('Functions can only run inline; use a named task')
        if dedupe:
            self.reap(kind, universe)
            existing = self.store.active_job(kind, universe)
            if existing:
                return Job(self.store, existing)
        row = {'id': uuid.uuid4().hex[:12], 'kind': kind, 'universe': universe, 'status': 'queued',
               'message': 'Waiting to start', 'params_json': json.dumps(to_jsonable(params or {})),
               'dedupe': int(dedupe), 'created_at': now_iso()}
        if not self.store.insert_job(row):  # another process queued the same job a moment ago
            existing = self.store.active_job(kind, universe)
            if existing:
                return Job(self.store, existing)
            raise RuntimeError('Could not queue the job')
        if self.backend == 'inline':
            if func is not None:
                self.runner.functions[row['id']] = func
            self._executor.submit(self.runner.execute, row['id'])
        else:
            self._queue.enqueue_call('api.worker.execute', args=(row['id'],), job_id=row['id'],
                                     timeout=TIMEOUTS.get(kind, 3600), result_ttl=3600, failure_ttl=7 * 86400,
                                     description=f'{kind} {universe}')
        return Job(self.store, row)

    # ---------------------------------------------------------------- query

    def get(self, job_id: str) -> Optional[Job]:
        row = self.store.get_job(job_id)
        if row and row['status'] in ACTIVE:
            self._reap_row(row)
            row = self.store.get_job(job_id)
        return Job(self.store, row) if row else None

    def list(self, universe: Optional[str] = None, limit: int = 50) -> List[Job]:
        return [Job(self.store, r) for r in self.store.list_jobs(universe, limit=limit)]

    def active(self, kind: str, universe: str) -> Optional[Job]:
        row = self.store.active_job(kind, universe)
        return Job(self.store, row) if row else None

    # --------------------------------------------------------------- health

    def ping(self) -> None:
        """Raise if the queue cannot be reached."""
        if self.backend == 'redis':
            self.redis.ping()

    def reap(self, kind: Optional[str] = None, universe: Optional[str] = None) -> int:
        """Mark jobs whose worker is gone as failed, so they do not block new ones."""
        rows = [r for r in self.store.list_jobs(universe, limit=200, statuses=list(ACTIVE))
                if kind is None or r['kind'] == kind]
        return sum(self._reap_row(r) for r in rows)

    def _reap_row(self, row: Dict[str, Any]) -> bool:
        if self.backend != 'redis':
            return False  # inline jobs live in this process; interrupted ones are handled at startup
        from rq.exceptions import NoSuchJobError
        from rq.job import Job as RQJob, JobStatus

        try:
            status = RQJob.fetch(row['id'], connection=self.redis).get_status()
        except NoSuchJobError:
            status = None
        lost = status is None or status in (JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELED)
        if not lost:
            return False
        reason = 'The worker stopped before finishing this job' if status else 'The job was lost from the queue'
        self.store.update_job(row['id'], status='failed', message='Failed', error=reason, finished_at=now_iso())
        logger.warning(f"Job {row['kind']}/{row['universe']} {row['id']}: {reason}")
        return True

    def _recover_interrupted(self) -> None:
        """Inline jobs that were queued or running when the server stopped will never finish."""
        for row in self.store.list_jobs(limit=500, statuses=list(ACTIVE)):
            self.store.update_job(row['id'], status='failed', message='Failed', finished_at=now_iso(),
                                  error='Interrupted: the server restarted before this job finished')

    def shutdown(self) -> None:
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)


@contextmanager
def redis_lock(redis, universe: str, timeout: int = 4 * 3600) -> Iterator[None]:
    """One job per universe at a time across all workers."""
    lock = redis.lock(f'ledger:universe:{universe}', timeout=timeout, blocking=True, blocking_timeout=None)
    lock.acquire()
    try:
        yield
    finally:
        try:
            lock.release()
        except Exception:  # expired: another worker may already hold it
            pass
