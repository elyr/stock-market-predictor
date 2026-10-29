"""
Monitoring tests: /metrics content, job and request metrics, values read from
the database, and JSON logs.
"""

import json
import logging
import time

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from api.logging_setup import JsonFormatter
from api.main import create_app
from api.settings import Settings


def wait(client: TestClient, job: dict, timeout: float = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job['status'] in ('succeeded', 'failed'):
            return job
        time.sleep(0.3)
    raise TimeoutError(job)


def scrape(client: TestClient) -> dict:
    """Samples as {(name, frozenset(labels)): value}."""
    response = client.get('/metrics')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/plain')
    samples = {}
    for family in text_string_to_metric_families(response.text):
        for s in family.samples:
            samples[(s.name, frozenset(s.labels.items()))] = s.value
    return samples


def value(samples: dict, name: str, **labels) -> float:
    return samples.get((name, frozenset(labels.items())))


@pytest.fixture(scope='module')
def client(fast_config_path, tmp_path_factory):
    directory = tmp_path_factory.mktemp('metrics')
    settings = Settings(config_path=fast_config_path, demo_mode=True, seed_demo=False,
                        database_path=str(directory / 'test.db'), frontend_dist=str(directory / 'none'),
                        internal_scheduler=False)
    with TestClient(create_app(settings)) as c:
        service = c.app.state.app_state.service('stocks')
        service.default_symbols = lambda s=service: s.pipeline.symbols[:12]
        yield c


def test_metrics_before_any_analysis(client):
    samples = scrape(client)
    assert value(samples, 'ledger_info', version='2.0.0', mode='demo') == 1
    # No analysis yet: no data or model values, but the scrape works
    assert value(samples, 'ledger_data_age_days', universe='stocks') is None
    assert value(samples, 'ledger_live_scored_runs', universe='stocks') == 0


def test_requests_are_counted_per_route_template(client):
    client.get('/api/stocks')
    client.get('/api/crypto')
    assert client.get('/api/bonds').status_code == 404
    samples = scrape(client)
    assert value(samples, 'ledger_http_requests_total', method='GET', route='/api/{universe}', status='200') >= 2
    assert value(samples, 'ledger_http_requests_total', method='GET', route='/api/{universe}', status='404') == 1
    assert value(samples, 'ledger_http_request_duration_seconds_count', method='GET', route='/api/{universe}') >= 2


def test_jobs_and_model_values_after_an_analysis(client):
    job = wait(client, client.post('/api/stocks/analysis', json={'top_n': 4}).json())
    assert job['status'] == 'succeeded', job['error']
    samples = scrape(client)
    assert value(samples, 'ledger_jobs_total', kind='analysis', universe='stocks', status='succeeded') == 1
    assert value(samples, 'ledger_job_duration_seconds_count', kind='analysis', universe='stocks') == 1
    assert value(samples, 'ledger_jobs_running', kind='analysis', universe='stocks') == 0
    assert value(samples, 'ledger_job_last_success_timestamp_seconds', kind='analysis',
                 universe='stocks') == pytest.approx(time.time(), abs=600)
    assert value(samples, 'ledger_data_age_days', universe='stocks') >= 0
    assert value(samples, 'ledger_model_rank_ic', universe='stocks') is not None
    assert value(samples, 'ledger_model_champion_version', universe='stocks') == 1
    assert value(samples, 'ledger_model_pinned', universe='stocks') == 0


def test_failed_jobs_are_counted(client):
    app_state = client.app.state.app_state
    job = app_state.jobs.submit('analysis', 'crypto', lambda job: 1 / 0)
    wait(client, job.to_dict())
    samples = scrape(client)
    assert value(samples, 'ledger_jobs_total', kind='analysis', universe='crypto', status='failed') == 1


def test_live_rank_ic_from_scored_runs(client):
    store = client.app.state.app_state.store
    for day, ic in (('2026-01-05', 0.1), ('2026-01-12', -0.04)):
        run_id = store.save_run('crypto', day, 5, 1, {}, [{'symbol': 'BTC-USD', 'rank': 1, 'composite_score': 1.0,
                                                           'entry_price': 1.0}])
        store.record_outcome(run_id, day, {'BTC-USD': 0.01}, 0.01, 0.0, ic)
    samples = scrape(client)
    assert value(samples, 'ledger_live_scored_runs', universe='crypto') == 2
    assert value(samples, 'ledger_live_rank_ic', universe='crypto') == pytest.approx(0.03)


def test_json_log_lines():
    record = logging.LogRecord('api.jobs', logging.INFO, __file__, 1, 'Job %s done', ('x',), None)
    record.job_id = 'abc123'
    line = json.loads(JsonFormatter().format(record))
    assert line['message'] == 'Job x done' and line['level'] == 'info' and line['logger'] == 'api.jobs'
    assert line['job_id'] == 'abc123' and line['time'].endswith('+00:00')
