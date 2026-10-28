"""
Tests for data cleaning, feature engineering and the synthetic data source.
"""

import numpy as np
import pandas as pd

from src.data import DataPreprocessor
from src.data.collector import normalize_news_item
from src.data.synthetic import SyntheticDataCollector, generate_market


def test_clean_fills_gaps_without_looking_ahead(ohlcv):
    data = ohlcv.copy()
    data.iloc[10, data.columns.get_loc('Close')] = np.nan
    cleaned = DataPreprocessor().clean_stock_data(data)

    assert not cleaned[['Open', 'High', 'Low', 'Close', 'Volume']].isna().any().any()
    # Forward-filled from the previous day, not back-filled from the next
    assert cleaned['Close'].iloc[10] == data['Close'].iloc[9]


def test_clean_replaces_price_spike_with_previous_value(ohlcv):
    data = ohlcv.copy()
    spike_day = 50
    data.iloc[spike_day, data.columns.get_loc('Close')] *= 3
    cleaned = DataPreprocessor().clean_stock_data(data)

    assert cleaned['Close'].iloc[spike_day] == data['Close'].iloc[spike_day - 1]
    assert cleaned['Close'].notna().all()


def test_clean_replaces_non_positive_volume(ohlcv):
    data = ohlcv.copy()
    data.iloc[5, data.columns.get_loc('Volume')] = 0
    cleaned = DataPreprocessor().clean_stock_data(data)
    assert (cleaned['Volume'] > 0).all()


def test_basic_features(ohlcv):
    features = DataPreprocessor().add_basic_features(ohlcv)
    for column in ('Price_Range', 'Daily_Return', 'Volatility_5d', 'Volume_Ratio'):
        assert column in features.columns
    expected = ohlcv['Close'].iloc[20] / ohlcv['Close'].iloc[19] - 1
    assert np.isclose(features['Daily_Return'].iloc[20], expected)


def test_target_is_next_day_move_and_unknown_on_last_row(ohlcv):
    target = DataPreprocessor().create_target_variable(ohlcv)

    assert np.isnan(target['Target_Up'].iloc[-1])
    assert np.isnan(target['Future_Return'].iloc[-1])
    went_up = ohlcv['Close'].iloc[11] > ohlcv['Close'].iloc[10]
    assert target['Target_Up'].iloc[10] == float(went_up)


def test_target_threshold(ohlcv):
    target = DataPreprocessor().create_target_variable(ohlcv, threshold=0.02)
    known = target.dropna(subset=['Future_Return'])
    assert ((known['Future_Return'] > 0.02) == (known['Target_Up'] == 1)).all()


def test_synthetic_data_is_deterministic_and_valid():
    a = generate_market(['AAA', 'BBB'], days=100, seed=5)
    b = generate_market(['AAA'], days=100, seed=5)

    pd.testing.assert_frame_equal(a['AAA'], b['AAA'])
    assert not a['AAA']['Close'].equals(a['BBB']['Close'])
    for frame in a.values():
        assert (frame['High'] >= frame[['Open', 'Close']].max(axis=1)).all()
        assert (frame['Low'] <= frame[['Open', 'Close']].min(axis=1)).all()
        assert (frame['Volume'] > 0).all()


def test_synthetic_collector_matches_collector_interface():
    collector = SyntheticDataCollector(days=200)
    data = collector.fetch_multiple_stocks(['AAA', 'BBB', '^VIX', 'XLK'], period='6mo')

    assert set(data) == {'AAA', 'BBB'}
    assert len(data['AAA']) == 126
    assert collector.fetch_company_info('AAA')['symbol'] == 'AAA'
    assert 'SPY' in collector.fetch_market_data()
    assert collector.get_stock_news('AAA') == []


def test_news_items_are_normalised_for_both_yfinance_formats():
    old = {'title': 'Old style', 'publisher': 'Wire', 'link': 'http://x'}
    new = {'content': {'title': 'New style', 'summary': 'Body',
                       'provider': {'displayName': 'Wire'}, 'canonicalUrl': {'url': 'http://y'}}}
    assert normalize_news_item(old)['title'] == 'Old style'
    assert normalize_news_item(new) == {'title': 'New style', 'summary': 'Body',
                                        'publisher': 'Wire', 'link': 'http://y'}
