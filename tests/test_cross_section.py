"""
Cross-sectional ranking model: features without lookahead, recovery of a
planted signal, no false discovery on a market without one, and the pipeline,
backtest and registry wiring.
"""

import numpy as np
import pandas as pd
import pytest

from src.backtest import Backtester
from src.data.synthetic import generate_market
from src.models.cross_section import (PREFIX, TARGET, CrossSectionPredictor, add_cross_section_features,
                                      gaussian_rank, make_predictor, raw_features)
from tests.conftest import SYMBOLS, make_ranker


def _prepared(reversal, days=700, n=40, seed=5):
    symbols = [f'S{i:02d}' for i in range(n)]
    market = generate_market(symbols, days=days, seed=seed, reversal=reversal)
    prepared = {}
    for s, d in market.items():
        df = d.copy()
        df['Future_Return'] = df['Close'].shift(-5) / df['Close'] - 1
        prepared[s] = df
    universe = pd.concat({s: d['Future_Return'] for s, d in prepared.items()}, axis=1).mean(axis=1)
    for d in prepared.values():
        d['Future_Excess'] = d['Future_Return'] - universe
        d['Target_Up_Rel'] = (d['Future_Excess'] > 0).astype(float).where(d['Future_Excess'].notna())
    return add_cross_section_features(prepared, horizon=5)


def _pooled(prepared):
    return pd.concat([d.assign(Symbol=s) for s, d in prepared.items()]).sort_index(kind='stable')


def test_gaussian_rank_is_per_date_and_bounded():
    panel = pd.DataFrame({'a': [1.0, 5.0], 'b': [2.0, np.nan], 'c': [3.0, 1.0], 'd': [4.0, 3.0]})
    ranked = gaussian_rank(panel)
    assert ranked.loc[0].is_monotonic_increasing
    assert np.isnan(ranked.loc[1, 'b'])
    assert ranked.loc[1, 'a'] > ranked.loc[1, 'd'] > ranked.loc[1, 'c']
    assert ranked.abs().max().max() < 2.4  # clipped at the 1st/99th percentile
    assert abs(ranked.loc[0].mean()) < 1e-9


def test_features_use_only_the_past():
    market = generate_market([f'S{i}' for i in range(10)], days=400, seed=2)
    close = pd.DataFrame({s: d['Close'] for s, d in market.items()})
    volume = pd.DataFrame({s: d['Volume'] for s, d in market.items()})
    full, _ = raw_features(close, volume)
    cut = close.index[300]
    partial, _ = raw_features(close[:cut], volume[:cut])
    for name in full:
        pd.testing.assert_frame_equal(full[name][:cut], partial[name], check_freq=False)


def test_crypto_style_momentum_and_market_factor():
    market = generate_market(['BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD'], days=300, seed=1)
    close = pd.DataFrame({s: d['Close'] for s, d in market.items()})
    volume = pd.DataFrame({s: d['Volume'] for s, d in market.items()})
    features, _ = raw_features(close, volume, market='BTC-USD', momentum='short', year=365)
    assert {'mom_30', 'mom_90'} <= set(features) and 'mom_12_1' not in features
    # Bitcoin against itself has beta 1
    assert features['low_beta']['BTC-USD'].dropna().round(6).eq(-1.0).all()


def test_recovers_a_planted_signal():
    model = CrossSectionPredictor({'training': {'min_samples': 100}})
    performance = model.train_evaluate_and_refit(_pooled(_prepared(reversal=0.2)))
    ensemble = performance['ensemble']
    assert ensemble['ic_mean'] > 0.04 and ensemble['ic_t_stat'] > 3
    weights = model.coefficients()
    assert max(weights, key=weights.get) == PREFIX + 'rev_1d'
    probabilities = model.predict(_pooled(_prepared(reversal=0.2)).tail(40))['probabilities']
    assert ((probabilities > 0.3) & (probabilities < 0.7)).all()  # honest, near 50%


def test_finds_nothing_where_there_is_nothing():
    model = CrossSectionPredictor({'training': {'min_samples': 100}})
    ensemble = model.train_evaluate_and_refit(_pooled(_prepared(reversal=0.0, seed=8)))['ensemble']
    assert abs(ensemble['ic_mean']) < 0.03
    assert abs(ensemble['ic_t_stat']) < 3


def test_explain_and_xgboost_challenger():
    model = CrossSectionPredictor({'training': {'min_samples': 100},
                                   'cross_section': {'xgboost': {'enabled': True, 'n_estimators': 30}}})
    pooled = _pooled(_prepared(reversal=0.2, days=400, n=20))
    model.train_evaluate_and_refit(pooled)
    assert set(model.models) == {'ridge', 'xgboost'}
    explanation = model.explain(pooled.tail(1))
    assert explanation and all(e['feature'].startswith(PREFIX) and e['label'] for e in explanation)
    prediction = model.predict(pooled.tail(20))
    assert set(prediction['individual_probabilities']) == {'ridge', 'xgboost'}


def test_make_predictor_kinds():
    assert make_predictor({}).kind == 'cross_section'
    assert make_predictor({'model': 'legacy'}).kind == 'legacy'
    with pytest.raises(ValueError):
        make_predictor({'model': 'oracle'})


def test_pipeline_ranks_with_the_model_alone(fast_config_path):
    ranker = make_ranker(fast_config_path, reversal=0.2, days=500)
    result = ranker.get_top_10_recommendations(SYMBOLS)
    rankings = result['full_rankings']
    assert ranker.predictor.kind == 'cross_section'
    assert any(c.startswith(PREFIX) for c in ranker.last_prepared[rankings['Symbol'][0]].columns)
    # The composite is the model's percentile score
    assert np.allclose(rankings['Composite_Score'], rankings['ML_Score'])
    assert result['analysis_summary']['top_features'][0]['feature'].startswith(PREFIX)
    assert rankings['Explanation'][0][0]['feature'].startswith(PREFIX)


def test_backtest_finds_the_planted_signal(fast_config_path):
    ranker = make_ranker(fast_config_path, reversal=0.2, days=600)
    prepared = ranker.fetch_and_prepare_data(SYMBOLS)
    result = Backtester(ranker, top_n=4, test_days=200, min_train_days=100).run(prepared)
    assert result.ic['ML only']['ic_mean'] > 0.03
    # The composite is the model's score; the hand-made momentum score bets against the signal
    assert result.ic['Composite (no costs)']['ic_mean'] == pytest.approx(result.ic['ML only']['ic_mean'])
    assert result.ic['Momentum only']['ic_mean'] < result.ic['ML only']['ic_mean']


def test_models_round_trip_through_export(fast_config_path, tmp_path):
    ranker = make_ranker(fast_config_path, reversal=0.2, days=400)
    prepared = ranker.fetch_and_prepare_data(SYMBOLS)
    ranker.train_ml_models(prepared)
    ranker.export_models(str(tmp_path))
    other = make_ranker(fast_config_path, reversal=0.2, days=400)
    other.import_models(str(tmp_path))
    assert other.predictor.kind == 'cross_section'
    latest = pd.concat([d.tail(1) for d in prepared.values()])
    np.testing.assert_allclose(ranker.predictor.predict(latest)['scores'], other.predictor.predict(latest)['scores'])


def test_legacy_model_ignores_cross_section_columns():
    from src.models.ml_models import select_feature_columns
    frame = pd.DataFrame({'RSI': [1.0], PREFIX + 'rev_1d': [0.1], TARGET: [0.2]})
    assert select_feature_columns(frame) == ['RSI']
