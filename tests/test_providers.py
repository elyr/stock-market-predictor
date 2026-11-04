"""Fallback price sources: Coinbase (crypto) and Alpha Vantage (stocks), used when Yahoo Finance fails."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.data import collector as collector_module
from src.data.providers import AlphaVantageProvider, CoinbaseProvider


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f'HTTP {self.status}')


def coinbase_get(calls):
    """Answers like Coinbase: newest first, one candle per day in [start, end)."""
    def get(url, params, timeout, headers):
        calls.append((url, params))
        start = datetime.fromisoformat(params['start'])
        end = datetime.fromisoformat(params['end'])
        days = []
        day = end - timedelta(days=1)
        while day >= start:
            t = int(day.timestamp())
            days.append([t, 90.0, 110.0, 95.0, 100.0 + day.day, 1234.0])
            day -= timedelta(days=1)
        return FakeResponse(days)
    return get


def test_coinbase_pages_through_long_histories():
    calls = []
    frame = CoinbaseProvider(get=coinbase_get(calls)).fetch('btc-usd', '2y')
    assert len(calls) == 3  # 731 days in pages of at most 300
    assert all('/products/BTC-USD/candles' in url and p['granularity'] == 86400 for url, p in calls)
    assert list(frame.columns) == ['Open', 'High', 'Low', 'Close', 'Volume', 'Symbol']
    assert frame.index.is_monotonic_increasing and frame.index.tz is None
    assert frame.index.is_unique and 700 < len(frame) <= 731
    assert (frame['Low'] <= frame['Close']).all() and (frame['Symbol'] == 'btc-usd').all()


def test_alpha_vantage_needs_a_key_and_reports_limits():
    assert not AlphaVantageProvider(key='').supports('AAPL')
    assert not AlphaVantageProvider(key='k').supports('BTC-USD')
    today = pd.Timestamp.now().normalize()
    series = {str((today - pd.Timedelta(days=i)).date()): {'1. open': '1', '2. high': '2', '3. low': '0.5',
                                                           '4. close': str(1 + i / 100), '5. volume': '10'}
              for i in range(10)}
    provider = AlphaVantageProvider(key='k', get=lambda url, params, timeout: FakeResponse({'Time Series (Daily)': series}))
    frame = provider.fetch('AAPL', '1mo')
    assert len(frame) == 10 and frame['Close'].iloc[-1] == 1.0
    limited = AlphaVantageProvider(key='secret', get=lambda url, params, timeout: FakeResponse(
        {'Information': 'You have reached the daily limit.'}))
    with pytest.raises(RuntimeError, match='daily limit') as error:
        limited.fetch('AAPL', '1mo')
    assert 'secret' not in str(error.value)


class BrokenTicker:
    def __init__(self, symbol):
        pass

    def history(self, period, interval):
        raise ConnectionError('Yahoo Finance is unreachable')


def test_collector_falls_back_when_yahoo_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(collector_module.yf, 'Ticker', BrokenTicker)
    monkeypatch.setattr(collector_module.time, 'sleep', lambda s: None)
    monkeypatch.delenv('ALPHA_VANTAGE_API_KEY', raising=False)
    config = tmp_path / 'config.yaml'
    config.write_text('api_config:\n  retry_attempts: 2\n')
    collector = collector_module.DataCollector(str(config))
    calls = []
    collector.providers = [CoinbaseProvider(get=coinbase_get(calls))]
    collector.reset_run_sources()

    frame = collector.fetch_stock_data('ETH-USD', '6mo')
    assert frame is not None and len(frame) > 150
    assert collector.run_sources == {'Coinbase': 1}
    assert collector.source_failures['Yahoo Finance'] == 1
    # A stock with no fallback configured: nothing, and the failure is counted
    assert collector.fetch_stock_data('AAPL', '6mo') is None
    assert collector.source_failures['Yahoo Finance'] == 2
    # Cached: no new requests
    before = len(calls)
    collector.fetch_stock_data('ETH-USD', '6mo')
    assert len(calls) == before


def test_fallback_can_be_turned_off(tmp_path):
    config = tmp_path / 'config.yaml'
    config.write_text('api_config:\n  fallback: false\n')
    assert collector_module.DataCollector(str(config)).providers == []
