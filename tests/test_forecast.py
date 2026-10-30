"""
Price range forecasts: calibration on unseen dates, no use of future prices,
storage and scoring, and the API.
"""

import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.settings import Settings
from src.data.synthetic import generate_market
from src.models.forecast import RangeForecaster, daily_volatility, horizons_for, inside, reliability
from tests.conftest import database_settings


def closes(n=25, days=500, seed=4, crypto=None):
    market = generate_market([f'S{i:02d}' for i in range(n)], days=days, seed=seed, crypto=crypto)
    return {s: d['Close'] for s, d in market.items()}


@pytest.mark.parametrize('crypto,periods', [(False, 252), (True, 365)])
def test_ranges_hold_about_as_often_as_promised_on_unseen_dates(crypto, periods):
    forecaster = RangeForecaster(periods_per_year=periods)
    evaluation = forecaster.fit(closes(crypto=crypto))
    assert set(evaluation) == {'day', 'week'}
    for horizon in evaluation.values():
        assert 0.42 <= horizon['coverage_50'] <= 0.58
        assert 0.85 <= horizon['coverage_90'] <= 0.95
        assert horizon['samples'] > 1000
    assert forecaster.horizons == horizons_for(periods)
    assert forecaster.horizons['week'] == (7 if crypto else 5)


def test_ranges_are_ordered_and_centred_on_todays_price():
    data = closes()
    forecaster = RangeForecaster()
    forecaster.fit(data)
    for f in forecaster.predict(data):
        assert f['q05'] < f['q25'] < f['q50'] < f['q75'] < f['q95']
        assert f['q50'] == pytest.approx(data[f['symbol']].iloc[-1])
    week = {f['symbol']: f for f in forecaster.predict(data) if f['horizon'] == 'week'}
    day = {f['symbol']: f for f in forecaster.predict(data) if f['horizon'] == 'day'}
    symbol = next(iter(week))
    assert week[symbol]['q95'] - week[symbol]['q05'] > day[symbol]['q95'] - day[symbol]['q05']


def test_no_future_prices_are_used():
    close = closes(n=1)['S00']
    cut = 300
    changed = close.copy()
    changed.iloc[cut + 1:] *= np.linspace(1, 3, len(changed) - cut - 1)  # a different future
    assert daily_volatility(close).iloc[:cut + 1].equals(daily_volatility(changed).iloc[:cut + 1])


def test_turbulent_assets_get_wider_ranges():
    data = closes(n=20)
    noisy = data['S00'].copy()
    returns = np.log(noisy).diff().fillna(0)
    data['NOISY'] = np.exp(np.log(noisy.iloc[0]) + (returns * 3).cumsum())
    forecaster = RangeForecaster()
    forecaster.fit(data)
    week = {f['symbol']: f for f in forecaster.predict(data) if f['horizon'] == 'week'}
    width = {s: (f['q95'] - f['q05']) / f['q50'] for s, f in week.items()}
    assert width['NOISY'] > 2 * width['S00']


def test_backtest_scores_replayed_ranges():
    forecaster = RangeForecaster()
    records = forecaster.backtest(closes(n=10), periods=20)
    assert records and all(r['target_date'] > r['base_date'] for r in records)
    stats = reliability(records)
    assert stats['scored'] == len(records) and 0.8 <= stats['coverage_90'] <= 1.0
    assert inside(105, {'q05': 90, 'q25': 98, 'q75': 103, 'q95': 110}) == {'inside_50': 0, 'inside_90': 1}
    assert reliability([]) == {'scored': 0, 'coverage_50': None, 'coverage_90': None}


# ----------------------------------------------------------------------- API

def wait(client, job, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job['status'] in ('succeeded', 'failed'):
            return job
        time.sleep(0.3)
    raise TimeoutError(job)


@pytest.fixture(scope='module')
def client(fast_config_path, tmp_path_factory, module_database):
    directory = tmp_path_factory.mktemp('forecast')
    settings = Settings(config_path=fast_config_path, demo_mode=True, seed_demo=False,
                        frontend_dist=str(directory / 'none'), internal_scheduler=False,
                        **database_settings(module_database, directory))
    with TestClient(create_app(settings)) as c:
        service = c.app.state.app_state.service('crypto')
        service.default_symbols = lambda s=service: s.pipeline.symbols[:12]
        yield c


def test_no_forecast_before_the_first_one(client):
    assert client.get('/api/crypto/forecast').status_code == 404


def test_analysis_forecasts_every_asset(client):
    job = wait(client, client.post('/api/crypto/analysis', json={'top_n': 4}).json())
    assert job['status'] == 'succeeded', job['error']
    view = client.get('/api/crypto/forecast').json()
    assert [h['key'] for h in view['horizons']] == ['day', 'week']
    assert [h['label'] for h in view['horizons']] == ['Next 24 hours', 'Next 7 days']
    assert len(view['assets']) == 12
    first = view['assets'][0]
    assert first['rank'] == 1 and first['beat_probability'] is not None and first['name']
    assert first['day']['q05'] < first['price'] < first['week']['q95']
    assert view['evaluation']['week']['coverage_90'] > 0.7
    assert view['reliability']['live']['day']['scored'] == 0  # nothing has matured yet

    detail = client.get(f"/api/crypto/assets/{first['symbol']}").json()
    assert detail['forecast']['week']['q95'] == first['week']['q95']


def test_refresh_job_and_scoring(client):
    service = client.app.state.app_state.service('crypto')
    closes_ = {s: d['Close'] for s, d in service.prepared.items()}
    # A forecast made 10 days ago has matured; it is scored at the next refresh
    old = {s: c.iloc[:-10] for s, c in closes_.items()}
    forecaster = RangeForecaster(periods_per_year=365)
    forecaster.fit(old)
    service.store.save_forecast_batch('crypto', max(c.index[-1] for c in old.values()).date().isoformat(),
                                      {'horizons': forecaster.horizons}, forecaster.predict(old))
    job = wait(client, client.post('/api/crypto/forecast').json())
    assert job['status'] == 'succeeded', job['error']
    assert job['result']['scored'] == 24       # 12 assets x 2 horizons
    view = client.get('/api/crypto/forecast').json()
    assert view['reliability']['live']['week']['scored'] == 12
    assert view['assets'][0]['reliability_source'] == 'live'
    metrics = client.get('/metrics').text
    assert 'ledger_forecast_coverage{horizon="week",level="90",universe="crypto"}' in metrics


def test_demo_history_is_marked_simulated(client):
    service = client.app.state.app_state.service('crypto')
    if client.get('/api/crypto/forecast').status_code == 404:  # when run on its own
        assert wait(client, client.post('/api/crypto/forecast').json())['status'] == 'succeeded'
    shown = client.get('/api/crypto/forecast').json()['created_at']
    assert service.backfill_forecasts(service.prepared or None, periods=10) > 0
    view = client.get('/api/crypto/forecast').json()
    assert view['reliability']['simulated']['day']['scored'] > 0
    # Replayed history never replaces the latest live forecast on the page
    assert view['created_at'] == shown
