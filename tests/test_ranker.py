"""
Tests for the stock and crypto pipelines: scoring, filtering, portfolio and ranking.
"""

import numpy as np
import pandas as pd
import pytest

from src.prediction import CryptoPipeline, StockPipeline, create_pipeline
from src.prediction.portfolio import select_portfolio
from src.prediction.stock_ranker import composite_score, percentile_scores
from src.utils.helpers import recommendation_label
from conftest import CRYPTO_SYMBOLS, SYMBOLS, make_ranker


@pytest.fixture(scope='module')
def stock_run(fast_config_path):
    ranker = make_ranker(fast_config_path)
    return ranker, ranker.get_top_10_recommendations(SYMBOLS, top_n=5)


@pytest.fixture(scope='module')
def crypto_run(fast_config_path):
    ranker = make_ranker(fast_config_path, universe='crypto')
    return ranker, ranker.get_top_10_recommendations(CRYPTO_SYMBOLS, top_n=4)


def test_create_pipeline(fast_config_path):
    assert isinstance(create_pipeline('stocks', fast_config_path), StockPipeline)
    assert isinstance(create_pipeline('crypto', fast_config_path), CryptoPipeline)
    with pytest.raises(ValueError):
        create_pipeline('bonds', fast_config_path)


def test_pipelines_are_independent(fast_config_path):
    stocks, crypto = create_pipeline('stocks', fast_config_path), create_pipeline('crypto', fast_config_path)
    assert stocks.predictor is not crypto.predictor
    assert stocks.model_path() != crypto.model_path()
    assert stocks.periods_per_year == 252 and crypto.periods_per_year == 365
    assert all(s.endswith('-USD') for s in crypto.symbols)
    assert not any(s.endswith('-USD') for s in stocks.symbols)


def test_stock_end_to_end(stock_run):
    ranker, rec = stock_run
    top, full, summary = rec['top_10'], rec['full_rankings'], rec['analysis_summary']

    assert len(top) == 5 and len(full) == len(SYMBOLS)
    assert full['Composite_Score'].is_monotonic_decreasing
    for column in ('Composite_Score', 'Technical_Score', 'ML_Score', 'Momentum_Score', 'Volume_Score'):
        assert full[column].between(0, 100).all(), column
    assert full['ML_Probability'].between(0, 1).all()
    assert full['RSI'].notna().all()
    assert top['Weight'].sum() == pytest.approx(1.0)
    assert ranker.ml_trained
    assert summary['universe'] == 'stocks' and summary['horizon_days'] == ranker.horizon
    assert 'ic_mean' in summary['model_quality']
    assert summary['volatility_model']['r2_model'] is not None
    assert isinstance(top.iloc[0]['Signals'], list)
    assert top.iloc[0]['Explanation'] and 'contribution' in top.iloc[0]['Explanation'][0]
    assert 'ROC_5d_vs_Universe' in ranker.last_prepared[SYMBOLS[0]].columns


def test_stock_portfolio_respects_sector_cap(stock_run):
    ranker, rec = stock_run
    cap = ranker.portfolio_config['max_per_sector']
    assert cap > 0
    assert rec['top_10']['Sector'].value_counts().max() <= cap


def test_crypto_end_to_end(crypto_run):
    ranker, rec = crypto_run
    top, full = rec['top_10'], rec['full_rankings']

    assert len(top) == 4 and set(full['Symbol']) <= set(CRYPTO_SYMBOLS)
    assert (full['Asset_Class'] == 'crypto').all()
    assert 'Bitcoin' in set(full['Company_Name'])
    assert full['Sector'].isin(['Store of value', 'Smart-contract platform', 'Payments', 'Meme',
                                'Oracle', 'Interoperability', 'Exchange token', 'Storage', 'DeFi', 'Other']).all()
    assert full['Sentiment_Score'].isna().all()  # sentiment does not apply to crypto
    prepared = ranker.last_prepared
    btc = prepared['BTC-USD']
    assert np.allclose(btc['Beta_BTC_30d'].dropna(), 1.0)
    assert 'ROC_20d_vs_BTC' in prepared['ETH-USD'].columns


def test_momentum_score_is_not_saturated(stock_run):
    momentum = stock_run[1]['full_rankings']['Momentum_Score']
    assert momentum.max() < 100 and momentum.nunique() > 3


def test_composite_renormalises_over_available_components():
    weights = {'a': 0.5, 'b': 0.3, 'c': 0.2}
    assert composite_score({'a': 80, 'b': 60, 'c': 40}, weights) == pytest.approx(66)
    assert composite_score({'a': 80, 'b': 60, 'c': None}, weights) == pytest.approx(72.5)
    assert composite_score({}, weights) == 50.0


def test_percentile_scores():
    scores = percentile_scores(pd.Series([0.4, 0.6, 0.5]))
    assert list(scores) == [0.0, 100.0, 50.0]


def test_select_portfolio_weights_and_cap():
    ranked = pd.DataFrame({
        'Composite_Score': [90, 85, 80, 75, 70],
        'Sector': ['Tech', 'Tech', 'Tech', 'Energy', 'N/A'],
        'Volatility': [0.2, 0.4, 0.3, 0.1, 0.2],
    }, index=list('ABCDE'))

    capped = select_portfolio(ranked, 3, max_per_sector=2, weighting='equal')
    assert list(capped.index) == ['A', 'B', 'D']
    assert capped['Weight'].tolist() == pytest.approx([1 / 3] * 3)

    inverse = select_portfolio(ranked, 2, weighting='inverse_volatility')
    assert inverse.loc['A', 'Weight'] == pytest.approx(2 / 3)
    assert inverse['Weight'].sum() == pytest.approx(1)

    unknown = select_portfolio(ranked.assign(Sector='N/A'), 5, max_per_sector=1)
    assert len(unknown) == 5  # unknown sectors are not capped


def test_filters(ranker):
    data = ranker.fetch_and_prepare_data(['AAA'])['AAA']
    assert ranker.apply_filters('AAA', data)
    assert not ranker.apply_filters('AAA', data.assign(Close=2.0))
    assert not ranker.apply_filters('AAA', data.assign(Volume=1000))
    assert not ranker.apply_filters('AAA', data, {'market_cap': 5e8})


def test_crypto_filters_allow_low_prices(fast_config_path):
    crypto = make_ranker(fast_config_path, universe='crypto')
    data = crypto.fetch_and_prepare_data(['DOGE-USD'])['DOGE-USD'].assign(Close=0.15)
    assert crypto.apply_filters('DOGE-USD', data)


def test_signals_are_described(ranker):
    data = ranker.fetch_and_prepare_data(['AAA'])['AAA'].copy()
    data.loc[data.index[-1], ['RSI', 'Volume_Ratio']] = [22.0, 2.5]
    notes = ranker.describe_signals(data)
    assert "RSI 22: oversold" in notes
    assert any('Volume 2.5x' in n for n in notes)


def test_save_recommendations(stock_run, tmp_path):
    ranker, rec = stock_run
    path = ranker.save_recommendations(rec, str(tmp_path / 'out' / 'picks.csv'))
    saved = pd.read_csv(path)
    assert list(saved['Symbol']) == list(rec['top_10']['Symbol'])


def test_scores_on_short_history_are_neutral(ranker):
    data = ranker.fetch_and_prepare_data(['AAA'])['AAA'].head(10)
    assert ranker.calculate_momentum_score(data) == 50.0
    assert ranker.calculate_volume_score(data) == 50.0


@pytest.mark.parametrize('score,confidence,label', [
    (80, 0.8, 'STRONG BUY'), (80, 0.5, 'HOLD/WATCH'), (70, 0.65, 'BUY'), (56, 0.0, 'HOLD/WATCH'), (40, 0.9, 'AVOID'),
])
def test_recommendation_labels(score, confidence, label):
    assert recommendation_label(score, confidence) == label


def test_empty_symbol_list_raises(ranker):
    ranker.universe_config['symbols'] = []
    with pytest.raises(ValueError):
        ranker.get_top_10_recommendations([])
