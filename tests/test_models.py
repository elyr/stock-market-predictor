"""
Tests for the ML models and evaluation helpers.
"""

import numpy as np
import pandas as pd
import pytest
import yaml

from src.models import ModelEvaluator, StockPredictor
from src.models.ml_models import select_feature_columns
from conftest import PROJECT_ROOT, make_ranker, SYMBOLS

FAST = {
    'random_forest': {'n_estimators': 30, 'max_depth': 4},
    'xgboost': {'n_estimators': 30},
    'neural_network': {'hidden_layers': [8], 'max_iter': 50},
    'training': {'cross_validate': False},
}


@pytest.fixture(scope='module')
def pooled(fast_config_path):
    ranker = make_ranker(fast_config_path, reversal=0.3)
    prepared = ranker.fetch_and_prepare_data(SYMBOLS[:8])
    frames = [d.assign(Symbol=s) for s, d in prepared.items()]
    return pd.concat(frames)


def test_accepts_config_yaml_shape():
    with open(f"{PROJECT_ROOT}/config/config.yaml") as f:
        section = yaml.safe_load(f)['ml_config']
    predictor = StockPredictor(section)
    assert predictor.config['random_forest']['n_estimators'] == section['models']['random_forest']['n_estimators']
    assert predictor.config['lstm']['enabled'] is False
    assert predictor.config['training']['test_size'] == section['training']['test_size']


def test_feature_selection_excludes_targets_and_price_levels(pooled):
    features = select_feature_columns(pooled)
    for leaky in ('Target_Up', 'Future_Return', 'Future_Close', 'Target_Return'):
        assert leaky not in features
    for level in ('Close', 'Open', 'Volume', 'SMA_20', 'EMA_50', 'MACD', 'ATR', 'OBV', 'BB_Upper'):
        assert level not in features
    for kept in ('Daily_Return', 'RSI', 'MACD_Pct', 'ATR_Pct', 'Price_Distance_SMA_20', 'Volume_Ratio'):
        assert kept in features
    assert not any(c.startswith('Pattern_') for c in features)


def test_split_is_chronological(pooled):
    predictor = StockPredictor(FAST)
    X_train, X_test, y_train, y_test, _ = predictor.prepare_data(pooled, test_size=0.25)

    known = pooled.dropna(subset=['Target_Up']).sort_index(kind='stable')
    dates = known.index.unique().sort_values()
    split_date = dates[int(len(dates) * 0.75)]
    assert len(X_train) == (known.index < split_date).sum()
    assert len(X_test) == (known.index >= split_date).sum()


def test_models_learn_planted_signal(pooled):
    predictor = StockPredictor(FAST)
    performance = predictor.train_all_models(pooled)

    assert set(performance) == {'random_forest', 'xgboost', 'neural_network'}
    best = max(p['test_accuracy'] - p['test_base_rate'] for p in performance.values())
    assert best > 0.03, "no model beat the base rate on data with a planted signal"
    top_feature = predictor.get_feature_importance('random_forest', top_n=5)
    assert any(name in ('Daily_Return', 'Log_Return', 'ROC_1d', 'Price_Change_Pct') for name, _ in top_feature)


def test_predict_ensemble_and_column_robustness(pooled):
    predictor = StockPredictor(FAST)
    predictor.train_all_models(pooled, test_size=0)
    latest = pooled.groupby('Symbol').tail(1)

    result = predictor.predict(latest)
    assert result['probabilities'].shape == (len(latest),)
    assert ((result['probabilities'] >= 0) & (result['probabilities'] <= 1)).all()
    assert set(result['individual_probabilities']) == set(predictor.models)

    # Column order and extra columns must not change predictions
    shuffled = latest[latest.columns[::-1]].assign(Unrelated=1.0)
    assert np.allclose(predictor.predict(shuffled)['probabilities'], result['probabilities'])


def test_refit_keeps_holdout_metrics_but_uses_all_rows(pooled):
    predictor = StockPredictor(FAST)
    performance = predictor.train_evaluate_and_refit(pooled)
    assert all('test_accuracy' in p for p in performance.values())
    assert predictor.model_performance == performance
    n_known = pooled['Target_Up'].notna().sum()
    assert predictor.scalers['main'].n_samples_seen_ == n_known


def test_insufficient_data_raises(pooled):
    with pytest.raises(ValueError):
        StockPredictor(FAST).prepare_data(pooled.head(50))


def test_save_and_load_roundtrip(pooled, tmp_path):
    predictor = StockPredictor(FAST)
    predictor.train_all_models(pooled, test_size=0)
    path = tmp_path / 'models.joblib'
    predictor.save_models(str(path))

    loaded = StockPredictor()
    loaded.load_models(str(path))
    latest = pooled.tail(5)
    assert np.allclose(loaded.predict(latest)['probabilities'], predictor.predict(latest)['probabilities'])


def test_evaluator_classification_metrics():
    y_true = np.array([0, 1, 1, 0, 1, 0])
    y_pred = np.array([0, 1, 0, 0, 1, 1])
    result = ModelEvaluator().evaluate_classification_model(y_true, y_pred, y_pred.astype(float))
    assert result['accuracy'] == pytest.approx(4 / 6)
    assert result['true_positives'] == 2
