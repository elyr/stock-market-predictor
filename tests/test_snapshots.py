"""
Snapshot tests: lock what an analysis produces on the synthetic market.

Refactors (splitting the ranker, the API service, the CLI) must not change any
number the app shows. These tests run fixed-seed analyses end to end and
compare them with snapshots recorded from the code *before* the change, in the
same environment. Snapshots are not committed: library versions (pandas, numpy)
move the numbers, so only a comparison in one environment is meaningful.

    git stash; UPDATE_SNAPSHOTS=1 python3 -m pytest -q tests/test_snapshots.py   # on main
    git stash pop; python3 -m pytest -q tests/test_snapshots.py                  # your change

Without recorded snapshots the tests are skipped. In CI, the Snapshots job of
the Tests workflow records them from the pull request's base and compares; a
pull request that changes the output on purpose gets the ``changes-output``
label, which skips that job.
"""

import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.settings import Settings
from src.backtest import Backtester
from tests.conftest import CRYPTO_SYMBOLS, SYMBOLS, make_ranker
from tests.test_api import wait

SNAPSHOTS = Path(os.environ.get('SNAPSHOT_DIR') or Path(__file__).parent / 'snapshots')
UPDATE = os.environ.get('UPDATE_SNAPSHOTS') == '1'

# Values that change from one run to the next without the analysis changing
VOLATILE_KEYS = {'id', 'run_id', 'analysis_id', 'job_id', 'batch_id', 'created_at', 'started_at', 'finished_at',
                 'updated_at', 'latest_run_at', 'generated_at', 'duration_seconds', 'elapsed',
                 'model_version', 'code_version', 'version', 'path', 'model_path', 'analysis_date', 'tracking_uri',
                 'git_commit'}
REL, ABS = 1e-5, 1e-8  # tolerance for floats (BLAS and library versions differ in the last digits)


def normalise(value: Any) -> Any:
    """JSON-safe copy without volatile keys; floats rounded to 10 significant digits."""
    if isinstance(value, dict):
        return {str(k): normalise(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
                if str(k).lower() not in VOLATILE_KEYS}
    if isinstance(value, (list, tuple)):
        return [normalise(v) for v in value]
    if isinstance(value, pd.DataFrame):
        return normalise(value.reset_index().to_dict(orient='records'))
    if isinstance(value, pd.Series):
        return normalise(value.to_dict())
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value).date())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return None
        return float(f'{value:.10g}')
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def assert_same(actual: Any, expected: Any, where: str = '') -> None:
    """Structural equality, with a tolerance on floats."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f'{where}: expected an object'
        assert set(actual) == set(expected), \
            f'{where}: keys differ: +{sorted(set(actual) - set(expected))} -{sorted(set(expected) - set(actual))}'
        for key in expected:
            assert_same(actual[key], expected[key], f'{where}.{key}')
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), \
            f'{where}: expected a list of {len(expected)}, got {len(actual) if isinstance(actual, list) else type(actual)}'
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert_same(a, e, f'{where}[{i}]')
    elif isinstance(expected, float) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
        assert math.isclose(actual, expected, rel_tol=REL, abs_tol=ABS), f'{where}: {actual} != {expected}'
    else:
        assert actual == expected, f'{where}: {actual!r} != {expected!r}'


def require_snapshot(name: str) -> None:
    """Skip before any work when there is nothing recorded to compare with."""
    if not UPDATE and not (SNAPSHOTS / f'{name}.json').exists():
        pytest.skip(f'no recorded snapshot {name}.json: record one on main with UPDATE_SNAPSHOTS=1')


def check_snapshot(name: str, value: Any) -> None:
    actual = normalise(value)
    path = SNAPSHOTS / f'{name}.json'
    if UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(actual, indent=1, sort_keys=True) + '\n')
        return
    require_snapshot(name)
    assert_same(actual, json.loads(path.read_text()), name)


def ranking_snapshot(result: dict) -> dict:
    return {'top': result['top_10'], 'rankings': result['full_rankings'],
            'summary': result['analysis_summary']}


# --------------------------------------------------------------- pipelines

@pytest.mark.slow
@pytest.mark.parametrize('universe,symbols,top_n', [('stocks', SYMBOLS, 5), ('crypto', CRYPTO_SYMBOLS, 4)])
def test_analysis_output_is_unchanged(fast_config_path, universe, symbols, top_n):
    require_snapshot(f'analysis_{universe}')
    ranker = make_ranker(fast_config_path, reversal=0.2, universe=universe)
    result = ranker.analyse(symbols, top_n=top_n)
    check_snapshot(f'analysis_{universe}', {**ranking_snapshot(result),
                                            'long_term': ranker.long_term_summary()})


@pytest.mark.slow
def test_backtest_output_is_unchanged(fast_config_path):
    require_snapshot('backtest_stocks')
    ranker = make_ranker(fast_config_path, reversal=0.2)
    result = Backtester(ranker, top_n=3, test_days=60).run_symbols(SYMBOLS[:12])
    check_snapshot('backtest_stocks', {'daily': result.daily, 'metrics': result.metrics,
                                       'ic': result.ic, 'picks': result.picks})


# --------------------------------------------------------------------- API

API_PATHS = ['analysis/latest', 'volatility', 'long-term', 'forecast', 'market', 'brief', 'models']


@pytest.fixture(scope='module')
def api_client(fast_config_path, tmp_path_factory):
    for universe in ('stocks', 'crypto'):
        require_snapshot(f'api_{universe}')
    settings = Settings(config_path=fast_config_path, demo_mode=True, seed_demo=False,
                        frontend_dist=str(tmp_path_factory.mktemp('nofrontend')),
                        database_path=str(tmp_path_factory.mktemp('snapdb') / 'test.db'))
    with TestClient(create_app(settings)) as client:
        for universe in ('stocks', 'crypto'):
            service = client.app.state.app_state.service(universe)
            service.default_symbols = lambda s=service: s.pipeline.symbols[:14]
            job = wait(client, client.post(f'/api/{universe}/analysis', json={'top_n': 5}).json())
            assert job['status'] == 'succeeded', job['error']
        yield client


@pytest.mark.slow
@pytest.mark.parametrize('universe', ['stocks', 'crypto'])
def test_api_responses_are_unchanged(api_client, universe):
    responses = {}
    for path in API_PATHS:
        response = api_client.get(f'/api/{universe}/{path}')
        responses[path] = {'status': response.status_code, 'body': response.json()}
    check_snapshot(f'api_{universe}', responses)
