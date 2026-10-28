"""
Tests for the return model, the volatility model and evaluation helpers.
"""

import numpy as np
import pandas as pd
import pytest
import yaml

from src.models import ModelEvaluator, StockPredictor
from src.models.ml_models import chronological_split, information_coefficient, select_feature_columns
from src.models.volatility import VolatilityForecaster
from conftest import PROJECT_ROOT, SYMBOLS, make_ranker

FAST = {
    'random_forest': {'n_estimators': 30, 'max_depth': 4},
    'xgboost': {'n_estimators': 30},
    'neural_network': {'hidden_layers': [8], 'max_iter': 50},
    'training': {'cross_validate': False, 'horizon': 1, 'target': 'relative'},
}


@pytest.fixture(scope='module')
def pooled(daily_config_path):
    ranker = make_ranker(daily_config_path, reversal=0.3)
    return ranker.pool(ranker.fetch_and_prepare_data(SYMBOLS[:10]))


def test_accepts_config_yaml_shape():
    with open(f"{PROJECT_ROOT}/config/config.yaml") as f:
        section = yaml.safe_load(f)['ml_config']
    predictor = StockPredictor(section)
    assert predictor.config['random_forest']['n_estimators'] == section['models']['random_forest']['n_estimators']
    assert predictor.config['lstm']['enabled'] is False
    assert predictor.horizon == section['training']['horizon']
    assert predictor.target_column == 'Target_Up_Rel'
    assert StockPredictor({'training': {'target': 'absolute'}}).target_column == 'Target_Up'


def test_feature_selection_excludes_targets_and_price_levels(pooled):
    features = select_feature_columns(pooled)
    for leaky in ('Target_Up', 'Target_Up_Rel', 'Future_Return', 'Future_Excess', 'Future_Vol',
                  'Target_Vol_Up', 'Universe_Future_Return', 'Future_Close'):
        assert leaky not in features
    for level in ('Close', 'Open', 'Volume', 'SMA_20', 'EMA_50', 'MACD', 'ATR', 'OBV', 'BB_Upper'):
        assert level not in features
    for kept in ('Daily_Return', 'RSI', 'MACD_Pct', 'ATR_Pct', 'Price_Distance_SMA_20',
                 'ROC_5d_vs_Universe', 'Market_Vol_5d'):
        assert kept in features
    assert not any(c.startswith('Pattern_') for c in features)


def test_chronological_split_has_purge_gap():
    index = pd.DatetimeIndex(np.repeat(pd.bdate_range('2025-01-01', periods=100), 3))
    train, test = chronological_split(index, test_size=0.2, purge_days=5)
    dates = index.unique()
    assert index[train].max() < index[test].min()
    gap = dates.get_loc(index[test].min()) - dates.get_loc(index[train].max())
    assert gap == 6  # 5 purged dates in between
    assert index[test].nunique() == 20


def test_models_learn_planted_signal(pooled):
    predictor = StockPredictor(FAST)
    performance = predictor.train_all_models(pooled)

    assert set(performance) == {'random_forest', 'xgboost', 'neural_network'}
    best_auc = max(p['test_auc'] for p in performance.values())
    assert best_auc > 0.53, "no model ranked better than chance on data with a planted signal"
    top = [name for name, _ in predictor.get_feature_importance('random_forest', top_n=6)]
    assert any(n in top for n in ('Daily_Return', 'Log_Return', 'ROC_1d', 'Price_Change_Pct'))


def test_evaluate_calibrate_and_refit(pooled):
    predictor = StockPredictor(FAST)
    performance = predictor.train_evaluate_and_refit(pooled)
    ensemble = performance['ensemble']

    assert ensemble['ic_mean'] > 0.03 and ensemble['ic_t_stat'] > 2
    assert ensemble['brier_calibrated'] <= ensemble['brier_raw'] + 1e-3
    assert ensemble['reliability'] and all(0 <= r['observed'] <= 1 for r in ensemble['reliability'])
    assert predictor.calibrator is not None
    # Refit uses every labelled row
    assert predictor.scalers['main'].n_samples_seen_ == pooled['Target_Up_Rel'].notna().sum()

    result = predictor.predict(pooled.tail(20))
    assert not np.allclose(result['probabilities'], result['raw_probabilities'])


def test_information_coefficient():
    dates = pd.DatetimeIndex(np.repeat(pd.bdate_range('2025-01-01', periods=30), 10))
    rng = np.random.default_rng(1)
    returns = rng.normal(size=300)
    assert information_coefficient(returns, returns, dates)['ic_mean'] == pytest.approx(1.0)
    noise = information_coefficient(rng.normal(size=300), returns, dates)
    assert abs(noise['ic_mean']) < 0.15 and noise['ic_days'] == 30


def test_predict_ensemble_and_column_robustness(pooled):
    predictor = StockPredictor(FAST)
    predictor.train_all_models(pooled, test_size=0)
    latest = pooled.groupby('Symbol').tail(1)

    result = predictor.predict(latest)
    assert result['probabilities'].shape == (len(latest),)
    assert ((result['probabilities'] >= 0) & (result['probabilities'] <= 1)).all()
    assert set(result['individual_probabilities']) == set(predictor.models)

    shuffled = latest[latest.columns[::-1]].assign(Unrelated=1.0)
    assert np.allclose(predictor.predict(shuffled)['probabilities'], result['probabilities'])


def test_explanations_are_shap_contributions(pooled):
    predictor = StockPredictor(FAST)
    predictor.train_all_models(pooled, test_size=0)
    row = pooled.tail(1)
    explanation = predictor.explain(row, top_n=200)

    assert explanation and {'feature', 'label', 'value', 'contribution'} <= set(explanation[0])
    sizes = [abs(e['contribution']) for e in explanation]
    assert sizes == sorted(sizes, reverse=True)
    # SHAP values plus the bias term add up to the model's log-odds output
    import xgboost as xgb
    X = predictor.scalers['main'].transform(row.reindex(columns=predictor.feature_columns).fillna(0))
    margin = predictor.models['xgboost'].get_booster().predict(xgb.DMatrix(X), output_margin=True)[0]
    contribs = predictor.models['xgboost'].get_booster().predict(xgb.DMatrix(X), pred_contribs=True)[0]
    assert sum(e['contribution'] for e in explanation) + contribs[-1] == pytest.approx(margin, abs=1e-4)


def test_insufficient_data_raises(pooled):
    with pytest.raises(ValueError):
        StockPredictor(FAST).prepare_data(pooled.head(50))


def test_save_and_load_roundtrip(pooled, tmp_path):
    predictor = StockPredictor(FAST)
    predictor.train_evaluate_and_refit(pooled)
    path = tmp_path / 'models.joblib'
    predictor.save_models(str(path))

    loaded = StockPredictor()
    loaded.load_models(str(path))
    latest = pooled.tail(5)
    assert np.allclose(loaded.predict(latest)['probabilities'], predictor.predict(latest)['probabilities'])


def test_volatility_model_beats_naive_forecast(pooled):
    forecaster = VolatilityForecaster(horizon=5)
    performance = forecaster.fit(pooled)

    assert performance['r2_model'] > performance['r2_naive']
    assert performance['auc'] > 0.55
    latest = pooled.groupby('Symbol').tail(1)
    forecast = forecaster.predict(latest)
    assert list(forecast.columns) == ['prob_vol_up', 'current_vol', 'forecast_vol']
    assert (forecast['forecast_vol'] > 0).all() and forecast['prob_vol_up'].between(0, 1).all()


def test_evaluator_classification_metrics():
    y_true = np.array([0, 1, 1, 0, 1, 0])
    y_pred = np.array([0, 1, 0, 0, 1, 1])
    result = ModelEvaluator().evaluate_classification_model(y_true, y_pred, y_pred.astype(float))
    assert result['accuracy'] == pytest.approx(4 / 6)
    assert result['true_positives'] == 2
