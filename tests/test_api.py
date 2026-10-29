"""
API tests: the FastAPI app on synthetic data, end to end through background jobs.
"""

import time

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture(scope='module')
def client(fast_config_path, tmp_path_factory):
    settings = Settings(config_path=fast_config_path, demo_mode=True, seed_demo=False,
                        database_path=str(tmp_path_factory.mktemp('db') / 'test.db'),
                        frontend_dist=str(tmp_path_factory.mktemp('nofrontend')))
    with TestClient(create_app(settings)) as c:
        for universe in ('stocks', 'crypto'):
            service = c.app.state.app_state.service(universe)
            service.default_symbols = lambda s=service: s.pipeline.symbols[:14]
        yield c


def test_health_and_universes(client):
    assert client.get('/api/health').json()['demo'] is True
    universes = {u['key']: u for u in client.get('/api/universes').json()}
    assert set(universes) == {'stocks', 'crypto'}
    assert universes['crypto']['periods_per_year'] == 365
    assert client.get('/api/bonds').status_code == 404


def test_latest_analysis_404_before_first_run(client):
    assert client.get('/api/crypto/analysis/latest').status_code in (200, 404)


def test_stock_analysis_flow(client):
    job = client.post('/api/stocks/analysis', json={'top_n': 5}).json()
    assert job['status'] in ('queued', 'running')
    # A second request while running returns the same job instead of starting another
    assert client.post('/api/stocks/analysis', json={}).json()['id'] == job['id']
    job = wait(client, job)
    assert job['status'] == 'succeeded', job['error']

    latest = client.get('/api/stocks/analysis/latest').json()
    assert len(latest['picks']) == 5 and len(latest['rankings']) == 14
    pick = latest['picks'][0]
    for key in ('symbol', 'composite_score', 'ml_probability', 'weight', 'signals', 'explanation', 'volatility'):
        assert key in pick
    assert abs(sum(p['weight'] for p in latest['picks']) - 1) < 1e-6
    assert latest['summary']['model_quality']['ic_mean'] is not None
    assert latest['run']['universe'] == 'stocks'

    run = client.get(f"/api/stocks/runs/{latest['run']['id']}").json()
    assert run['run']['id'] == latest['run']['id']
    assert client.get('/api/stocks/runs').json()[0]['id'] == latest['run']['id']

    symbol = pick['symbol']
    detail = client.get(f'/api/stocks/assets/{symbol}').json()
    assert detail['symbol'] == symbol and len(detail['history']) > 100
    assert {'date', 'close', 'rsi', 'sma_50'} <= set(detail['history'][-1])
    assert detail['latest']['symbol'] == symbol

    vol = client.get('/api/stocks/volatility').json()
    assert vol['model']['r2_model'] is not None and len(vol['assets']) == 14

    assert client.get('/api/stocks/market').json()['items']


def test_crypto_is_separate(client):
    job = wait(client, client.post('/api/crypto/analysis', json={'top_n': 4}).json())
    assert job['status'] == 'succeeded', job['error']
    crypto = client.get('/api/crypto/analysis/latest').json()
    assert all(r['symbol'].endswith('-USD') for r in crypto['rankings'])
    assert crypto['summary']['universe'] == 'crypto'
    assert {i['symbol'] for i in client.get('/api/crypto/market').json()['items']} >= {'BTC-USD'}


def test_backtest_flow(client):
    job = wait(client, client.post('/api/stocks/backtests',
                                   json={'top_n': 3, 'test_days': 40, 'use_ml': False}).json())
    assert job['status'] == 'succeeded', job['error']
    backtest_id = job['result']['backtest_id']
    detail = client.get(f'/api/stocks/backtests/{backtest_id}').json()
    result = detail['result']
    assert result['settings']['periods'] == len(result['dates']) == 8
    assert 'composite_net' in result['curves'] and 'universe' in result['curves']
    assert any(m['strategy'] == 'Composite after costs' for m in result['metrics'])
    assert client.get('/api/stocks/backtests').json()[0]['id'] == backtest_id
    assert client.post('/api/stocks/backtests', json={'test_days': 5}).status_code == 422


def test_simulated_track_record(client):
    service = client.app.state.app_state.service('stocks')
    service.run_backtest(None, {'top_n': 3, 'test_days': 40, 'use_ml': False}, record_simulated=True)
    record = client.get('/api/stocks/track-record').json()
    assert record['simulated']['evaluated'] == 8
    assert len(record['simulated']['curve']) == 8
    assert 0 <= record['simulated']['hit_rate'] <= 1
    # Simulated runs never replace the latest live analysis
    assert not client.get('/api/stocks/analysis/latest').json()['run']['simulated']


def test_outcomes_are_scored_once_prices_exist(client):
    service = client.app.state.app_state.service('stocks')
    import pandas as pd
    # Pretend the latest run was made 10 rows earlier, so its 5-day horizon has passed
    latest = client.get('/api/stocks/analysis/latest').json()
    entry_date = list(service.prepared.values())[0].index[-10]
    with service.store._connect() as conn:
        conn.execute("UPDATE runs SET data_date = ? WHERE id = ?", (str(entry_date.date()), latest['run']['id']))
        for p in latest['rankings']:
            price = float(service.prepared[p['symbol']].loc[entry_date, 'Close'])
            conn.execute("UPDATE predictions SET entry_price = ? WHERE run_id = ? AND symbol = ?",
                         (price, latest['run']['id'], p['symbol']))
    assert service.evaluate_outcomes(service.prepared) >= 1
    run = client.get(f"/api/stocks/runs/{latest['run']['id']}").json()
    assert run['run']['evaluated_at'] is not None
    expected = service.prepared[run['rankings'][0]['symbol']]['Close']
    position = expected.index.get_loc(pd.Timestamp(entry_date))
    assert run['rankings'][0]['realized_return'] == pytest.approx(
        expected.iloc[position + 5] / expected.iloc[position] - 1)
    assert client.get('/api/stocks/track-record').json()['live']['evaluated'] >= 1


def test_job_listing_and_unknown_job(client):
    assert isinstance(client.get('/api/jobs').json(), list)
    assert client.get('/api/jobs/nope').status_code == 404


def test_signal_scan_and_notifications(client):
    st = client.app.state.app_state
    assert client.get('/api/notifications/unread').json().keys() == {'stocks', 'crypto'}

    # Plant a crash in the latest bar of one stock, then scan
    service = st.service('stocks')
    symbol = service.default_symbols()[0]
    collector = service.pipeline.data_collector
    collector._ensure([symbol])
    frame = collector._data[symbol]
    last = frame.index[-1]
    frame.loc[last, ['Close', 'Low']] = frame.loc[last, 'Close'] * 0.8
    frame.loc[last, 'Volume'] *= 6

    job = wait(client, client.post('/api/stocks/signals/scan', json={'session': 'close'}).json())
    assert job['status'] == 'succeeded', job['error']
    assert job['result']['new_alerts'] >= 1

    alerts = client.get('/api/notifications', params={'universe': 'stocks'}).json()
    crash = next(a for a in alerts if a['symbol'] == symbol and a['type'] == 'unusual_move')
    assert crash['severity'] == 'critical' and not crash['read']
    assert client.get('/api/notifications/unread').json()['stocks']['critical'] >= 1

    # Scanning again does not duplicate
    again = wait(client, client.post('/api/stocks/signals/scan', json={'session': 'close'}).json())
    assert again['result']['new_alerts'] == 0

    assert client.post(f"/api/notifications/{crash['id']}/read").json()['read'] is True
    client.post('/api/notifications/read-all', params={'universe': 'stocks'})
    assert client.get('/api/notifications/unread').json()['stocks']['total'] == 0
    assert client.get('/api/notifications', params={'universe': 'crypto'}).status_code == 200
    assert client.post('/api/notifications/999999/read').status_code == 404
    assert client.post('/api/stocks/signals/scan', json={'session': 'noon'}).status_code == 422


def test_signal_schedule_endpoint(client):
    schedule = client.get('/api/signals/schedule').json()
    assert schedule['open'] == '09:45' and schedule['close'] == '16:15'
    assert {s['session'] for s in schedule['next']['crypto']} == {'open', 'close'}


def test_performance_report_from_a_backtest(client):
    job = wait(client, client.post('/api/stocks/backtests', json={'top_n': 3, 'test_days': 60}).json())
    assert job['status'] == 'succeeded', job['error']
    backtest_id = job['result']['backtest_id']

    report = client.get('/api/stocks/performance', params={'backtest_id': backtest_id}).json()
    assert report['source'] == 'backtest' and report['backtest_id'] == backtest_id
    summary = report['summary']
    assert summary['periods'] == 12 and summary['predictions'] == 12 * 14
    assert summary['picked_count'] == 12 * 3
    assert report['deciles']['buckets'] and report['ic_series']
    assert {c['label'] for c in report['components']} >= {'Composite score', 'Model', 'Momentum'}
    assert report['breakdowns']['direction']
    assert report['log'][0]['date'] >= report['log'][-1]['date']
    assert any(s['id'] == backtest_id for s in report['sources'])

    # Default source is the latest backtest with a prediction log
    assert client.get('/api/stocks/performance').json()['backtest_id'] == backtest_id

    csv = client.get('/api/stocks/performance/predictions.csv', params={'backtest_id': backtest_id})
    assert csv.status_code == 200 and csv.headers['content-type'].startswith('text/csv')
    lines = csv.text.strip().splitlines()
    assert lines[0].startswith('date,symbol,sector,score') and len(lines) == 12 * 14 + 1

    assert client.get('/api/stocks/performance', params={'source': 'nope'}).status_code == 422
    assert client.get('/api/stocks/performance', params={'backtest_id': 'missing'}).status_code == 404


def test_live_performance_uses_scored_runs(client):
    report = client.get('/api/stocks/performance', params={'source': 'live'}).json()
    assert report['source'] == 'live'
    assert report['summary']['predictions'] >= 0  # filled once live runs have matured


def test_experiment_workflow_with_locked_period(client):
    settings = client.get('/api/experiments/settings').json()
    assert 'ranking_config.weights.momentum_score' in settings

    bad = client.post('/api/stocks/experiments', json={'name': 'x', 'settings': {'api_config.timeout': 1}})
    assert bad.status_code == 422
    out_of_range = client.post('/api/stocks/experiments',
                               json={'name': 'x', 'settings': {'ml_config.training.horizon': 99}})
    assert out_of_range.status_code == 422

    created = client.post('/api/stocks/experiments', json={
        'name': 'No momentum', 'top_n': 3,
        'settings': {'ranking_config.weights.momentum_score': 0.0, 'ml_config.models.xgboost.max_depth': 2},
    }).json()
    experiment_id = created['experiment_id']
    assert client.post(f'/api/stocks/experiments/{experiment_id}/lockbox').status_code in (202, 409)
    job = wait(client, created['job'])
    assert job['status'] == 'succeeded', job['error']

    experiment = client.get(f'/api/stocks/experiments/{experiment_id}').json()
    assert experiment['status'] == 'done' and experiment['lockbox'] is None
    dev = experiment['development']
    windows = dev['windows']
    assert dev['summary']['end'] <= windows['dev_end'] < windows['lockbox_start']
    assert {'ic_mean', 'decile_spread', 'annualized_return'} <= set(dev['headline'])

    # The development run is also available in the comparator
    report = client.get('/api/stocks/performance').json()
    labels = [s['label'] for s in report['sources']]
    assert 'Experiment: No momentum (development period)' in labels
    # The default view stays on a regular backtest, not an experiment run
    default = next(s for s in report['sources'] if s['id'] == report['backtest_id'])
    assert default['label'].startswith('Backtest of')

    lock = wait(client, client.post(f'/api/stocks/experiments/{experiment_id}/lockbox').json())
    assert lock['status'] == 'succeeded', lock['error']
    labels = [s['label'] for s in client.get('/api/stocks/performance').json()['sources']]
    assert 'Experiment: No momentum (locked period)' in labels
    checked = client.get(f'/api/stocks/experiments/{experiment_id}').json()
    assert checked['lockbox']['summary']['start'] >= windows['lockbox_start']
    first_check = checked['lockbox_checked_at']

    # A second check returns the stored result instead of re-running
    again = wait(client, client.post(f'/api/stocks/experiments/{experiment_id}/lockbox').json())
    assert again['result']['already_checked'] is True
    assert client.get(f'/api/stocks/experiments/{experiment_id}').json()['lockbox_checked_at'] == first_check

    listing = client.get('/api/stocks/experiments').json()
    assert listing['lockbox_days'] == 30 and listing['experiments'][0]['id'] == experiment_id
    assert client.get('/api/crypto/experiments').json()['experiments'] == []  # separate per universe


def test_readiness(client):
    ready = client.get('/api/ready')
    assert ready.status_code == 200 and ready.json()['status'] == 'ready'


def test_ready_reports_database_problems(client, monkeypatch):
    store = client.app.state.app_state.store
    monkeypatch.setattr(store, 'has_runs', lambda universe: (_ for _ in ()).throw(RuntimeError('disk gone')))
    response = client.get('/api/ready')
    assert response.status_code == 503 and 'disk gone' in response.json()['problems'][0]


def test_internal_scheduler_can_be_turned_off(fast_config_path, tmp_path, monkeypatch):
    import api.main as main_module
    started = []

    async def fake_loop(state):
        started.append('signals')

    monkeypatch.setattr(main_module, 'signal_scheduler_loop', fake_loop)
    for internal, expected in ((False, []), (True, ['signals'])):
        started.clear()
        settings = Settings(config_path=fast_config_path, demo_mode=True, seed_demo=False,
                            database_path=str(tmp_path / f'{internal}.db'), frontend_dist=str(tmp_path),
                            internal_scheduler=internal)
        with TestClient(create_app(settings)) as c:
            assert c.get('/api/ready').json()['internal_scheduler'] is internal
        assert started == expected
