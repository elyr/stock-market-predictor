"""
Model registry tests: MLflow on a local SQLite store, the pipeline's model
export and import, and the API flow (train, roll back, pin, unpin).
"""

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.settings import Settings
from src.models.registry import ModelRegistry, safe_uri
from tests.conftest import make_ranker


def wait(client: TestClient, job: dict, timeout: float = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job['status'] in ('succeeded', 'failed'):
            return job
        time.sleep(0.3)
    raise TimeoutError(job)


def local_registry(tmp_path, demo=True) -> ModelRegistry:
    return ModelRegistry(f"sqlite:///{tmp_path / 'mlflow.db'}", artifact_root=str(tmp_path / 'artifacts'),
                         demo=demo)


# ------------------------------------------------------------------ registry

def test_register_promote_pin_and_download(tmp_path):
    registry = local_registry(tmp_path)
    model_dir = tmp_path / 'model'
    model_dir.mkdir()
    (model_dir / 'models.joblib').write_text('version one')

    assert registry.versions('crypto') == [] and registry.champion('crypto') is None
    first = registry.register('crypto', str(model_dir), {'data_date': '2026-01-02', 'horizon_days': 5},
                              {'quality': {'ic_mean': 0.04, 'nested': {'deep': 1}}, 'skip': 'text'},
                              tags={'git_commit': 'abc1234'})
    (model_dir / 'models.joblib').write_text('version two')
    second = registry.register('crypto', str(model_dir), {'data_date': '2026-01-09'}, {})

    assert (first['version'], second['version']) == ('1', '2')
    assert registry.name('crypto') == 'ledger-crypto-demo'
    assert registry.champion('crypto') == '2' and not registry.pinned('crypto')
    versions = registry.versions('crypto')
    assert [v['version'] for v in versions] == ['2', '1']
    assert versions[1]['metrics']['quality.ic_mean'] == pytest.approx(0.04)
    assert versions[1]['metrics']['quality.nested.deep'] == 1
    assert versions[1]['git_commit'] == 'abc1234' and versions[1]['data_date'] == '2026-01-02'
    assert versions[0]['champion'] and not versions[1]['champion']

    # Roll back: version 1 becomes the champion and is pinned
    summary = registry.promote('crypto', '1')
    assert summary['champion'] == '1' and summary['pinned'] is True
    path = registry.download('crypto', '1', str(tmp_path / 'download'))
    assert open(f'{path}/models.joblib').read() == 'version one'

    registry.set_pinned('crypto', False)
    assert not registry.pinned('crypto')
    registry.set_pinned('crypto', False)  # unpinning twice is fine

    # Universes and demo/live data are kept apart
    assert registry.versions('stocks') == []
    assert local_registry(tmp_path, demo=False).versions('crypto') == []


def test_register_without_promotion_keeps_the_champion(tmp_path):
    registry = local_registry(tmp_path)
    model_dir = tmp_path / 'm'
    model_dir.mkdir()
    (model_dir / 'x').write_text('x')
    registry.register('stocks', str(model_dir), {}, {})
    registry.register('stocks', str(model_dir), {}, {}, promote=False)
    assert registry.champion('stocks') == '1'


def test_safe_uri_hides_credentials():
    assert safe_uri('https://user:secret@mlflow.example.com') == 'https://mlflow.example.com'
    assert safe_uri('sqlite:///data/mlflow.db') == 'sqlite:///data/mlflow.db'


# ------------------------------------------------------------ export/import

def test_exported_models_predict_the_same_without_retraining(fast_config_path, tmp_path):
    trained = make_ranker(fast_config_path, reversal=0.2)
    symbols = trained.symbols[:12]
    before = trained.rank_stocks(symbols)
    assert trained.ml_trained
    trained.export_models(str(tmp_path / 'models'))

    loaded = make_ranker(fast_config_path, reversal=0.2)
    loaded.import_models(str(tmp_path / 'models'))
    loaded.train_ml_models = lambda *a, **k: pytest.fail('should not retrain')
    after = loaded.rank_stocks(symbols)

    merged = before.set_index('Symbol').join(after.set_index('Symbol'), rsuffix='_loaded')
    assert np.allclose(merged['ML_Probability'], merged['ML_Probability_loaded'])
    assert np.allclose(merged['Vol_Forecast'], merged['Vol_Forecast_loaded'])
    assert loaded.ml_performance['ensemble']['ic_mean'] == trained.ml_performance['ensemble']['ic_mean']


def test_loaded_models_refuse_missing_features(fast_config_path, tmp_path):
    trained = make_ranker(fast_config_path)
    trained.rank_stocks(trained.symbols[:10])
    trained.export_models(str(tmp_path / 'models'))
    loaded = make_ranker(fast_config_path)
    loaded.import_models(str(tmp_path / 'models'))
    loaded.predictor.feature_columns = [*loaded.predictor.feature_columns, 'Feature_That_Is_Gone']
    with pytest.raises(ValueError, match='retrain'):
        loaded.rank_stocks(loaded.symbols[:10])


def test_models_of_another_universe_are_refused(fast_config_path, tmp_path):
    stocks = make_ranker(fast_config_path)
    stocks.rank_stocks(stocks.symbols[:10])
    stocks.export_models(str(tmp_path / 'models'))
    crypto = make_ranker(fast_config_path, universe='crypto')
    with pytest.raises(ValueError, match="belong to 'stocks'"):
        crypto.import_models(str(tmp_path / 'models'))


# ----------------------------------------------------------------------- API

def make_client(config_path, directory, **extra):
    settings = Settings(config_path=config_path, demo_mode=True, seed_demo=False,
                        database_path=str(directory / 'test.db'), frontend_dist=str(directory / 'none'),
                        internal_scheduler=False, **extra)
    return TestClient(create_app(settings))


@pytest.fixture(scope='module')
def client(fast_config_path, tmp_path_factory):
    with make_client(fast_config_path, tmp_path_factory.mktemp('registry')) as c:
        service = c.app.state.app_state.service('crypto')
        service.default_symbols = lambda s=service: s.pipeline.symbols[:12]
        yield c


def analyse(client) -> dict:
    job = wait(client, client.post('/api/crypto/analysis', json={'top_n': 4}).json())
    assert job['status'] == 'succeeded', job['error']
    return client.get('/api/crypto/analysis/latest').json()['summary']['model']


def test_api_train_roll_back_pin_and_unpin(client):
    empty = client.get('/api/crypto/models').json()
    assert empty['enabled'] and empty['versions'] == [] and empty['name'] == 'ledger-crypto-demo'
    assert empty['tracking_uri'].startswith('sqlite:///')

    # Each analysis trains and registers a new champion
    assert analyse(client) == {'version': '1', 'reused': False, 'registry': 'ledger-crypto-demo',
                               'run_id': client.get('/api/crypto/models').json()['versions'][0]['run_id']}
    assert analyse(client)['version'] == '2'
    models = client.get('/api/crypto/models').json()
    assert models['champion'] == '2' and not models['pinned']
    assert [v['version'] for v in models['versions']] == ['2', '1']
    assert 'quality.ic_mean' in models['versions'][0]['metrics']
    assert models['versions'][0]['params']['universe'] == 'crypto'

    # Roll back to version 1: it is pinned, and analyses use it without training
    rolled = client.post('/api/crypto/models/1/promote', json={}).json()
    assert rolled['champion'] == '1' and rolled['pinned']
    service = client.app.state.app_state.service('crypto')
    service.pipeline.train_ml_models = lambda *a, **k: pytest.fail('a pinned model must not retrain')
    model = analyse(client)
    assert model['version'] == '1' and model['reused'] is True
    assert len(client.get('/api/crypto/models').json()['versions']) == 2
    assert client.get('/api/crypto/models').json()['loaded_version'] == '1'
    del service.pipeline.train_ml_models  # back to the class method

    # Unpin: the next analysis trains again and becomes version 3
    assert client.post('/api/crypto/models/unpin').json()['pinned'] is False
    assert analyse(client) | {'run_id': None} == {'version': '3', 'reused': False,
                                                  'registry': 'ledger-crypto-demo', 'run_id': None}
    assert client.get('/api/crypto/models').json()['champion'] == '3'


def test_api_unknown_version(client):
    assert client.post('/api/crypto/models/999/promote', json={}).status_code == 404


def test_registry_can_be_turned_off(fast_config_path, tmp_path):
    with make_client(fast_config_path, tmp_path, model_registry='off') as c:
        assert c.get('/api/stocks/models').json() == {'enabled': False, 'versions': [], 'champion': None,
                                                      'pinned': False}
        assert c.post('/api/stocks/models/1/promote', json={}).status_code == 409
        assert c.post('/api/stocks/models/unpin').status_code == 409
