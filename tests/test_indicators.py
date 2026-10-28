"""
Tests for technical indicators and chart patterns.
"""

import numpy as np
import pandas as pd
import yaml

from src.analysis import TechnicalAnalyzer
from conftest import PROJECT_ROOT


def _frame(close, volume=1e6):
    close = pd.Series(close, index=pd.bdate_range('2025-01-01', periods=len(close)), dtype=float)
    return pd.DataFrame({'Open': close, 'High': close * 1.01, 'Low': close * 0.99,
                         'Close': close, 'Volume': volume})


def test_accepts_config_yaml_shape():
    with open(f"{PROJECT_ROOT}/config/config.yaml") as f:
        section = yaml.safe_load(f)['technical_analysis']
    analyzer = TechnicalAnalyzer(section)

    # Values from the nested 'indicators' block are used; missing ones get defaults
    assert analyzer.config['rsi']['period'] == section['indicators']['rsi']['period']
    assert analyzer.config['stochastic']['k_period'] == 14
    assert analyzer.config['adx']['period'] == 14


def test_all_indicators_computed_with_yaml_config(ohlcv):
    with open(f"{PROJECT_ROOT}/config/config.yaml") as f:
        section = yaml.safe_load(f)['technical_analysis']
    result = TechnicalAnalyzer(section).calculate_all_indicators(ohlcv)

    for column in ('RSI', 'MACD', 'MACD_Signal', 'BB_Position', 'Stoch_K', 'CCI', 'MFI',
                   'ATR', 'ATR_Pct', 'OBV', 'ADX', 'DI_Plus', 'MACD_Pct', 'RSI_Oversold'):
        assert column in result.columns, column
        assert result[column].iloc[-1] == result[column].iloc[-1], f"{column} is NaN on the last row"


def test_rsi_bounds_and_extremes(ohlcv):
    analyzer = TechnicalAnalyzer()
    rsi = analyzer.calculate_rsi(ohlcv).dropna()
    assert rsi.between(0, 100).all()

    rising = analyzer.calculate_rsi(_frame(np.arange(1, 60))).dropna()
    falling = analyzer.calculate_rsi(_frame(np.arange(60, 1, -1))).dropna()
    assert (rising == 100).all()
    assert (falling < 1).all()


def test_rsi_uses_wilder_smoothing():
    close = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
             45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64]
    rsi = TechnicalAnalyzer().calculate_rsi(_frame(close), period=14)
    # Values from the StockCharts "RSI" worked example spreadsheet (Wilder's method)
    expected = [70.46, 66.25, 66.48, 69.35, 66.29, 57.92]
    assert rsi.iloc[:14].isna().all()
    assert np.allclose(rsi.iloc[14:].round(2), expected)


def test_bollinger_band_ordering(ohlcv):
    bands = TechnicalAnalyzer().calculate_bollinger_bands(ohlcv)
    valid = bands['BB_Upper'].notna()
    assert (bands['BB_Upper'][valid] >= bands['BB_Middle'][valid]).all()
    assert (bands['BB_Middle'][valid] >= bands['BB_Lower'][valid]).all()


def test_adx_range_and_trend_direction():
    up = _frame(np.linspace(100, 160, 80))
    adx = TechnicalAnalyzer().calculate_adx(up)
    assert adx['ADX'].dropna().between(0, 100).all()
    assert adx['DI_Plus'].iloc[-1] > adx['DI_Minus'].iloc[-1]


def test_patterns_are_a_snapshot_on_the_last_row(ohlcv):
    result = TechnicalAnalyzer().calculate_all_indicators(ohlcv)
    pattern_cols = [c for c in result.columns if c.startswith('Pattern_')]
    assert pattern_cols
    # Patterns describe the latest window only; earlier rows must not carry them
    assert not result[pattern_cols].iloc[:-1].any().any()


def test_bullish_flag_detection_is_price_scale_free():
    analyzer = TechnicalAnalyzer()
    pole = np.linspace(100, 115, 10)
    flag = 115 + 0.05 * np.sin(np.arange(10))
    for scale in (0.1, 1, 30):
        patterns = analyzer.detect_chart_patterns(_frame(np.concatenate([pole, flag]) * scale))
        assert patterns['bullish_flag'], f"flag missed at price scale {scale}"
