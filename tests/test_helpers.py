"""
Tests for utility helpers, plus optional live-data checks.
"""

import pytest

from src.utils import helpers


def test_calculate_percentage_change():
    assert helpers.calculate_percentage_change(100, 110) == 10.0
    assert helpers.calculate_percentage_change(100, 90) == -10.0
    assert helpers.calculate_percentage_change(0, 10) == 0.0


def test_format_currency():
    assert helpers.format_currency(1234.56) == "$1,234.56"
    assert helpers.format_currency(1234.56, "EUR") == "1,234.56 EUR"


def test_format_large_number():
    assert helpers.format_large_number(1234) == "1.2K"
    assert helpers.format_large_number(1234567) == "1.2M"
    assert helpers.format_large_number(1234567890) == "1.2B"


def test_safe_divide():
    assert helpers.safe_divide(10, 2) == 5.0
    assert helpers.safe_divide(10, 0) == 0.0
    assert helpers.safe_divide(10, 0, -1) == -1


def test_normalize_score():
    assert helpers.normalize_score(50, 0, 100) == 50.0
    assert helpers.normalize_score(25, 0, 100) == 25.0
    assert helpers.normalize_score(150, 0, 100) == 100.0


def test_validate_symbols():
    valid = helpers.validate_symbols(['AAPL', 'msft', 'BRK-B', 'BF.B', 'GOOGL123', '', 'TSL@'])
    assert valid == ['AAPL', 'MSFT', 'BRK-B', 'BF.B']


@pytest.mark.network
def test_live_yahoo_pipeline():
    """End-to-end on real data. Run with RUN_NETWORK_TESTS=1."""
    from src.prediction import StockRanker

    ranker = StockRanker()
    ranker.use_sentiment = False
    result = ranker.get_top_10_recommendations(['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'JPM', 'XOM'], top_n=3)
    assert len(result['top_10']) == 3
    assert result['top_10']['RSI'].notna().all()
    assert ranker.ml_trained
