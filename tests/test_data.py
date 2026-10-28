"""
Tests for data cleaning, feature engineering, targets and the synthetic data source.
"""

import numpy as np
import pandas as pd

from src.data import DataPreprocessor
from src.data.collector import normalize_news_item
from src.data.preprocessor import add_relative_targets
from src.data.synthetic import SyntheticDataCollector, generate_market


def test_clean_fills_gaps_without_looking_ahead(ohlcv):
    data = ohlcv.copy()
    data.iloc[10, data.columns.get_loc('Close')] = np.nan
    cleaned = DataPreprocessor().clean_stock_data(data)

    assert not cleaned[['Open', 'High', 'Low', 'Close', 'Volume']].isna().any().any()
    assert cleaned['Close'].iloc[10] == data['Close'].iloc[9]


def test_clean_replaces_price_spike_with_previous_value(ohlcv):
    data = ohlcv.copy()
    data.iloc[50, data.columns.get_loc('Close')] *= 3
    cleaned = DataPreprocessor().clean_stock_data(data)
    assert cleaned['Close'].iloc[50] == data['Close'].iloc[49]


def test_clean_replaces_non_positive_volume(ohlcv):
    data = ohlcv.copy()
    data.iloc[5, data.columns.get_loc('Volume')] = 0
    assert (DataPreprocessor().clean_stock_data(data)['Volume'] > 0).all()


def test_basic_features(ohlcv):
    features = DataPreprocessor().add_basic_features(ohlcv)
    for column in ('Price_Range', 'Daily_Return', 'Volatility_5d', 'Volatility_60d', 'Volume_Ratio', 'Abs_Return'):
        assert column in features.columns
    expected = ohlcv['Close'].iloc[20] / ohlcv['Close'].iloc[19] - 1
    assert np.isclose(features['Daily_Return'].iloc[20], expected)


def test_target_horizon_and_unknown_tail(ohlcv):
    target = DataPreprocessor().create_target_variable(ohlcv, horizon=5)

    assert target['Target_Up'].iloc[-5:].isna().all()
    assert target['Target_Up'].iloc[:-5].notna().all()
    expected = ohlcv['Close'].iloc[15] / ohlcv['Close'].iloc[10] - 1
    assert np.isclose(target['Future_Return'].iloc[10], expected)
    assert target['Target_Up'].iloc[10] == float(expected > 0)


def test_target_threshold(ohlcv):
    target = DataPreprocessor().create_target_variable(ohlcv, threshold=0.02)
    known = target.dropna(subset=['Future_Return'])
    assert ((known['Future_Return'] > 0.02) == (known['Target_Up'] == 1)).all()


def test_relative_targets_remove_the_market_move():
    raw = generate_market(['AAA', 'BBB', 'CCC'], days=80, seed=2)
    pre = DataPreprocessor()
    prepared = {s: pre.create_target_variable(d, horizon=3) for s, d in raw.items()}
    relative = add_relative_targets(prepared)

    excess = pd.concat({s: d['Future_Excess'] for s, d in relative.items()}, axis=1).dropna()
    assert np.allclose(excess.sum(axis=1), 0)  # equal-weight excess returns cancel out
    for d in relative.values():
        known = d.dropna(subset=['Future_Excess'])
        assert ((known['Future_Excess'] > 0) == (known['Target_Up_Rel'] == 1)).all()
        assert d['Target_Up_Rel'].iloc[-3:].isna().all()


def test_volatility_targets(ohlcv):
    data = DataPreprocessor().add_volatility_targets(ohlcv, horizon=5)
    returns = ohlcv['Close'].pct_change()
    assert np.isclose(data['Future_Vol'].iloc[100], returns.iloc[101:106].std())
    assert data['Target_Vol_Up'].iloc[-5:].isna().all()


def test_synthetic_data_is_deterministic_and_valid():
    a = generate_market(['AAA', 'BBB'], days=100, seed=5)
    b = generate_market(['AAA'], days=100, seed=5)

    pd.testing.assert_frame_equal(a['AAA'], b['AAA'])
    assert not a['AAA']['Close'].equals(a['BBB']['Close'])
    for frame in a.values():
        assert (frame['High'] >= frame[['Open', 'Close']].max(axis=1)).all()
        assert (frame['Low'] <= frame[['Open', 'Close']].min(axis=1)).all()
        assert (frame['Volume'] > 0).all()


def test_synthetic_volatility_clusters():
    returns = generate_market(['AAA'], days=2000, seed=9)['AAA']['Close'].pct_change().dropna()
    size = returns.abs()
    assert size.autocorr(lag=1) > 0.1  # big moves follow big moves


def test_synthetic_crypto_trades_every_day():
    data = generate_market(['BTC-USD', 'ETH-USD'], days=60, seed=1)
    index = data['BTC-USD'].index
    assert (index.to_series().diff().dropna() == pd.Timedelta(days=1)).all()
    assert data['ETH-USD']['Close'].pct_change().std() > 0.02


def test_synthetic_collector_matches_collector_interface():
    collector = SyntheticDataCollector(days=200)
    data = collector.fetch_multiple_stocks(['AAA', 'BBB', '^VIX', 'XLK'], period='6mo')

    assert set(data) == {'AAA', 'BBB'}
    assert len(data['AAA']) == 126
    assert collector.fetch_company_info('AAA')['symbol'] == 'AAA'
    assert 'SPY' in collector.fetch_market_data()
    assert collector.get_stock_news('AAA') == []
    assert len(collector.fetch_stock_data('BTC-USD', '6mo')) > 126  # 7-day calendar


def test_news_items_are_normalised_for_both_yfinance_formats():
    old = {'title': 'Old style', 'publisher': 'Wire', 'link': 'http://x'}
    new = {'content': {'title': 'New style', 'summary': 'Body',
                       'provider': {'displayName': 'Wire'}, 'canonicalUrl': {'url': 'http://y'}}}
    assert normalize_news_item(old)['title'] == 'Old style'
    assert normalize_news_item(new) == {'title': 'New style', 'summary': 'Body',
                                        'publisher': 'Wire', 'link': 'http://y'}
