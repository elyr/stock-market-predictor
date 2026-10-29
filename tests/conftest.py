"""
Shared fixtures. Everything here runs offline on synthetic data.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.data.synthetic import SyntheticDataCollector, generate_market  # noqa: E402
from src.prediction import create_pipeline  # noqa: E402

SYMBOLS = [f"TST{chr(65 + i)}" for i in range(16)]
CRYPTO_SYMBOLS = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD', 'DOGE-USD', 'AVAX-USD',
                  'LINK-USD', 'DOT-USD', 'LTC-USD', 'BCH-USD', 'XLM-USD']


def pytest_configure(config):
    config.addinivalue_line("markers", "network: needs live Yahoo Finance access (set RUN_NETWORK_TESTS=1)")


def pytest_collection_modifyitems(config, items):
    if os.environ.get('RUN_NETWORK_TESTS') == '1':
        return
    skip = pytest.mark.skip(reason="network test; set RUN_NETWORK_TESTS=1 to run")
    for item in items:
        if 'network' in item.keywords:
            item.add_marker(skip)


def load_project_config() -> dict:
    with open(os.path.join(PROJECT_ROOT, 'config', 'config.yaml')) as f:
        return yaml.safe_load(f)


def write_fast_config(path, **training) -> str:
    """The project config with small, fast models (same structure as the real file)."""
    config = load_project_config()
    models = config['ml_config']['models']
    models['random_forest'].update({'n_estimators': 40, 'max_depth': 4})
    models['xgboost'].update({'n_estimators': 40})
    models['neural_network'].update({'hidden_layers': [16], 'max_iter': 60})
    config['ml_config']['training'].update({'cross_validate': False, **training})
    for universe in config['universes'].values():
        universe['use_sentiment'] = False
    config['tracking'] = {'database': str(path.parent / 'predictions.db')}
    config['experiments'] = {'test_days': 60, 'lockbox_days': 30}
    path.write_text(yaml.safe_dump(config))
    return str(path)


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    """One synthetic stock, 300 trading days."""
    return generate_market(['ABC'], days=300, seed=1)['ABC']


@pytest.fixture(scope='session')
def fast_config_path(tmp_path_factory) -> str:
    return write_fast_config(tmp_path_factory.mktemp('config') / 'config.yaml')


@pytest.fixture(scope='session')
def daily_config_path(tmp_path_factory) -> str:
    """Fast config predicting 1 day ahead (where the planted daily signal is strongest)."""
    return write_fast_config(tmp_path_factory.mktemp('config1d') / 'config.yaml', horizon=1)


def make_ranker(config_path: str, reversal: float = 0.0, seed: int = 3, days: int = 400,
                universe: str = 'stocks'):
    collector = SyntheticDataCollector(days=days, seed=seed, reversal=reversal)
    return create_pipeline(universe, config_path, data_collector=collector)


@pytest.fixture
def ranker(fast_config_path):
    return make_ranker(fast_config_path)


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(0)


# ----------------------------------------------------------------- databases
#
# Tests that take ``database`` run on SQLite, and also on PostgreSQL when
# TEST_DATABASE_URL points at a server where they may create databases
# (CI sets it; locally: TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres).

def _postgres_admin_url():
    return os.environ.get('TEST_DATABASE_URL', '').strip()


@pytest.fixture(params=['sqlite', 'postgresql'])
def database(request, tmp_path):
    """A fresh, empty database: a SQLite file path or a PostgreSQL URL."""
    if request.param == 'sqlite':
        yield str(tmp_path / 'test.db')
        return
    admin = _postgres_admin_url()
    if not admin:
        pytest.skip('set TEST_DATABASE_URL to also run on PostgreSQL')
    yield from _fresh_postgres(admin)


def _fresh_postgres(admin: str):
    import uuid

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from api.db import database_url

    url = make_url(database_url('', admin))
    name = f'ledger_test_{uuid.uuid4().hex[:10]}'
    engine = create_engine(url, isolation_level='AUTOCOMMIT')
    with engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE {name}'))
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        with engine.connect() as conn:
            conn.execute(text(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{name}'"))
            conn.execute(text(f'DROP DATABASE IF EXISTS {name}'))
        engine.dispose()


@pytest.fixture(scope='module')
def module_database(tmp_path_factory):
    """One database for a module: PostgreSQL when TEST_DATABASE_URL is set, else SQLite."""
    admin = _postgres_admin_url()
    if admin and os.environ.get('TEST_API_ON_POSTGRES') == '1':
        yield from _fresh_postgres(admin)
    else:
        yield str(tmp_path_factory.mktemp('db') / 'test.db')


def database_settings(database: str, directory) -> dict:
    """
    Settings arguments for a database from the fixtures: a SQLite path or a
    URL. With a URL, the SQLite path still anchors the local model registry
    (files next to it), so it goes in the test's folder.
    """
    if '://' in database:
        return {'database_url': database, 'database_path': str(directory / 'registry.db')}
    return {'database_path': database}
