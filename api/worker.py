"""
Worker process: runs the jobs the server puts on the Redis queue.

    JOB_QUEUE=redis REDIS_URL=redis://localhost:6379/0 \\
    DATABASE_URL=postgresql+psycopg://... python -m api.worker

It uses the same settings as the server (environment variables, see
api/settings.py) and the same database. Each universe's models stay in memory
between jobs, so the worker runs jobs in its own process (RQ's SimpleWorker)
instead of forking a new one per job. A Redis lock per universe keeps jobs of
one universe in order, however many workers run. Prometheus metrics for the
jobs it runs are served on ``WORKER_METRICS_PORT`` (default 9101).
"""

import logging
import os
import sys
import threading
from typing import Dict, Optional

logger = logging.getLogger('api.worker')

_state: Optional['WorkerState'] = None
_state_lock = threading.Lock()


class WorkerState:
    """What a worker needs to run jobs: settings, database, services, metrics."""

    def __init__(self):
        from redis import Redis

        from api.jobs import Runner, redis_lock
        from api.metrics import Metrics
        from api.notifications import Notifier
        from api.service import UniverseService, create_registry
        from api.settings import Settings
        from api.store import NotificationStore, Store
        from src.data.collector import load_config
        from src.signals import merge_signal_config

        self.settings = settings = Settings.from_env()
        self.redis = Redis.from_url(settings.redis_url)
        self.store = Store(settings.database_url or settings.database_path)
        self.metrics = Metrics()
        self.registry = create_registry(settings)
        signals = merge_signal_config(load_config(settings.config_path).get('signals'))
        self.notifier = Notifier(NotificationStore(self.store), channels=[], cooldown_hours=signals['cooldown_hours'])
        self.services: Dict[str, UniverseService] = {}

        def service(universe: str) -> UniverseService:
            if universe not in self.services:
                self.services[universe] = UniverseService(universe, settings, self.store, notifier=self.notifier,
                                                          registry=self.registry, metrics=self.metrics)
            return self.services[universe]

        self.runner = Runner(self.store, service, lambda universe: redis_lock(self.redis, universe), self.metrics)


def state() -> WorkerState:
    global _state
    with _state_lock:
        if _state is None:
            _state = WorkerState()
        return _state


def execute(job_id: str) -> None:
    """Entry point RQ calls for each job (see api/jobs.py, JobManager.submit)."""
    state().runner.execute(job_id)


def main() -> int:
    from prometheus_client import start_http_server
    from rq import Queue, SimpleWorker

    from api.jobs import QUEUE_NAME
    from api.logging_setup import configure_logging
    from api.settings import Settings

    settings = Settings.from_env()
    configure_logging(settings.log_format or 'text', settings.log_level)
    if settings.job_queue != 'redis':
        logger.error('The worker needs JOB_QUEUE=redis and REDIS_URL')
        return 2
    worker_state = state()
    port = int(os.environ.get('WORKER_METRICS_PORT', '9101'))
    if port:
        start_http_server(port, registry=worker_state.metrics.registry)
    queue = Queue(QUEUE_NAME, connection=worker_state.redis)
    worker = SimpleWorker([queue], connection=worker_state.redis)
    logger.info(f"Worker {worker.name} waiting for jobs on '{QUEUE_NAME}' "
                f"(database {worker_state.store.url}, metrics on :{port})")

    # RQ handles SIGTERM (sent by Kubernetes) itself: it finishes the current job, then stops
    worker.work(with_scheduler=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
