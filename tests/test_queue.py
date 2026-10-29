"""
Jobs on a Redis queue run by worker processes (JOB_QUEUE=redis).

Uses the Redis server at TEST_REDIS_URL when set (CI), else an in-memory fake.
"""

import os
import threading
import time
import types

import pytest
from rq import Queue, SimpleWorker

import api.worker
from api.jobs import QUEUE_NAME, JobManager, Runner, redis_lock
from api.store import Store


@pytest.fixture
def redis():
    url = os.environ.get('TEST_REDIS_URL', '').strip()
    if url:
        from redis import Redis
        connection = Redis.from_url(url)
        connection.flushdb()
        yield connection
        connection.flushdb()
    else:
        import fakeredis
        yield fakeredis.FakeRedis()


class FakeService:
    def __init__(self, universe, calls):
        self.universe, self.calls = universe, calls

    def run_analysis(self, job, top_n=None, symbols=None):
        job.message = 'Ranking'
        self.calls.append((self.universe, 'analysis', top_n))
        return {'run_id': 'r1', 'top_n': top_n}

    def scan_signals(self, job, session='close', lookback=1):
        raise RuntimeError('data source down')


@pytest.fixture
def setup(redis, database, monkeypatch):
    """A store, a server-side JobManager and a worker that share the queue."""
    store = Store(database)
    calls = []
    services = {}
    runner = Runner(store, lambda u: services.setdefault(u, FakeService(u, calls)),
                    lambda universe: redis_lock(redis, universe))
    monkeypatch.setattr(api.worker, '_state', types.SimpleNamespace(runner=runner))
    manager = JobManager(store, backend='redis', redis=redis)
    worker = SimpleWorker([Queue(QUEUE_NAME, connection=redis)], connection=redis)
    return types.SimpleNamespace(store=store, manager=manager, worker=worker, calls=calls, redis=redis)


def test_worker_runs_queued_jobs(setup):
    job = setup.manager.submit('analysis', 'stocks', {'top_n': 4})
    assert job.status == 'queued'
    # A second request while it waits returns the same job
    assert setup.manager.submit('analysis', 'stocks', {'top_n': 9}).id == job.id
    failing = setup.manager.submit('scan', 'crypto', {'session': 'open'}, dedupe=False)

    setup.worker.work(burst=True)

    done = setup.manager.get(job.id)
    assert done.status == 'succeeded' and done.result == {'run_id': 'r1', 'top_n': 4}
    assert done.message == 'Done' and setup.store.get_job(job.id)['worker']
    assert setup.calls == [('stocks', 'analysis', 4)]
    failed = setup.manager.get(failing.id)
    assert failed.status == 'failed' and failed.error == 'data source down'
    # Finished: a new request starts a new job
    assert setup.manager.submit('analysis', 'stocks').id != job.id


def test_a_job_lost_by_the_queue_does_not_block_new_ones(setup):
    job = setup.manager.submit('analysis', 'stocks')
    Queue(QUEUE_NAME, connection=setup.redis).empty()       # e.g. Redis restarted without its data
    assert setup.manager.get(job.id).status == 'failed'
    assert 'lost' in setup.manager.get(job.id).error
    assert setup.manager.submit('analysis', 'stocks').id != job.id


def test_functions_cannot_be_queued(setup):
    with pytest.raises(ValueError, match='inline'):
        setup.manager.submit('analysis', 'stocks', func=lambda job: None)
    with pytest.raises(ValueError, match='Unknown job kind'):
        setup.manager.submit('mine-bitcoin', 'crypto')


def test_one_job_per_universe_across_workers(redis):
    order = []

    def hold(name, seconds):
        with redis_lock(redis, 'stocks'):
            order.append(f'{name} start')
            time.sleep(seconds)
            order.append(f'{name} end')

    first = threading.Thread(target=hold, args=('a', 0.5))
    first.start()
    time.sleep(0.1)
    second = threading.Thread(target=hold, args=('b', 0))
    second.start()
    with redis_lock(redis, 'crypto'):  # another universe is not blocked
        order.append('crypto')
    first.join()
    second.join()
    assert order == ['a start', 'crypto', 'a end', 'b start', 'b end']


def test_ready_reports_the_queue(redis, fast_config_path, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import api.jobs
    from api.main import create_app
    from api.settings import Settings

    original = api.jobs.JobManager.__init__

    def with_fake(self, *args, **kwargs):  # the app connects by URL; give it this Redis instead
        kwargs['redis'] = redis
        original(self, *args, **kwargs)
    monkeypatch.setattr(api.jobs.JobManager, '__init__', with_fake)
    settings = Settings(config_path=fast_config_path, demo_mode=True, seed_demo=False,
                        database_path=str(tmp_path / 'q.db'), frontend_dist=str(tmp_path / 'none'),
                        internal_scheduler=False, job_queue='redis', redis_url='redis://unused')
    with TestClient(create_app(settings)) as client:
        ready = client.get('/api/ready').json()
        assert ready['status'] == 'ready' and ready['job_queue'] == 'redis'
        job = client.post('/api/crypto/analysis', json={}).json()
        assert job['status'] == 'queued'
        assert Queue(QUEUE_NAME, connection=redis).count == 1
