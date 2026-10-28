"""
Synthetic market data for offline demos and tests.

Prices follow a one-factor model: each stock's daily return is a shared market
return times the stock's beta, plus idiosyncratic noise. Optionally a known,
learnable signal is planted (short-term mean reversion: tomorrow's return leans
against today's) so tests can check that the ML models and the backtest find
real edge, and find none when there is none.

Nothing here is real market data. ``SyntheticDataCollector`` mirrors the parts
of :class:`DataCollector` the ranker and backtester use, so it can be passed in
wherever a live collector is expected.
"""

import zlib
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

SECTORS = ['Technology', 'Healthcare', 'Financial Services', 'Consumer Cyclical',
           'Industrials', 'Energy', 'Consumer Defensive', 'Utilities']

PERIOD_DAYS = {'5d': 5, '1mo': 21, '3mo': 63, '6mo': 126, '1y': 252, '2y': 504, '5y': 1260}


def generate_market(symbols: List[str], days: int = 504, seed: int = 42,
                    reversal: float = 0.0, end: str = '2026-10-27') -> Dict[str, pd.DataFrame]:
    """
    Generate daily OHLCV data for several stocks over the same business days.

    Args:
        symbols: Ticker names to generate
        days: Number of trading days
        seed: Random seed (same seed gives identical data)
        reversal: Strength of the planted mean-reversion signal. 0 means returns
            are unpredictable; 0.3 means about 30% of each day's idiosyncratic
            move reverses the next day.
        end: Last date in the series

    Returns:
        Dictionary of symbol -> DataFrame with Open, High, Low, Close, Volume, Symbol
    """
    dates = pd.bdate_range(end=end, periods=days)
    market = np.random.default_rng(seed).normal(0.0004, 0.01, days)

    result = {}
    for symbol in symbols:
        # Each symbol's own stream: same symbol + seed always gives the same series
        rng = np.random.default_rng([seed, zlib.crc32(symbol.encode())])
        beta = rng.uniform(0.6, 1.4)
        vol = rng.uniform(0.012, 0.025)
        noise = rng.normal(0, vol, days)
        idio = np.zeros(days)
        for t in range(days):
            idio[t] = noise[t] - (reversal * idio[t - 1] if t > 0 else 0.0)
        returns = beta * market + idio

        close = rng.uniform(20, 400) * np.exp(np.cumsum(returns))
        open_ = close / np.exp(returns) * np.exp(rng.normal(0, vol / 4, days))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, days)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, days)))
        base_volume = rng.uniform(2e6, 3e7)
        volume = base_volume * np.exp(rng.normal(0, 0.3, days) + 8 * np.abs(returns))

        result[symbol] = pd.DataFrame({
            'Open': open_, 'High': high, 'Low': low, 'Close': close,
            'Volume': volume.round(), 'Symbol': symbol,
        }, index=dates)
    return result


class SyntheticDataCollector:
    """
    Drop-in stand-in for :class:`DataCollector` serving synthetic data.

    Supports the methods the ranker, sentiment analyzer and backtester call.
    News is empty and market data is derived from the synthetic stocks.
    """

    def __init__(self, symbols: Optional[List[str]] = None, days: int = 504,
                 seed: int = 42, reversal: float = 0.0):
        self.days = days
        self.seed = seed
        self.reversal = reversal
        self._data: Dict[str, pd.DataFrame] = {}
        if symbols:
            self._ensure(symbols)

    # Index/ETF tickers the sentiment module asks for; synthetic mode has no such data
    NON_STOCK_SYMBOLS = {'SPY', 'QQQ', 'DIA', 'GLD', 'TLT', 'XLK', 'XLV', 'XLF', 'XLY', 'XLC',
                         'XLI', 'XLP', 'XLE', 'XLU', 'XLRE', 'XLB'}

    def _ensure(self, symbols: List[str]) -> None:
        missing = [s for s in symbols if s not in self._data]
        if missing:
            self._data.update(generate_market(missing, self.days, self.seed, self.reversal))

    def fetch_stock_data(self, symbol: str, period: str = '2y') -> Optional[pd.DataFrame]:
        if symbol.startswith('^') or symbol in self.NON_STOCK_SYMBOLS:
            return None
        self._ensure([symbol])
        rows = PERIOD_DAYS.get(period, self.days)
        return self._data[symbol].tail(rows).copy()

    def fetch_multiple_stocks(self, symbols: List[str], period: str = '2y') -> Dict[str, pd.DataFrame]:
        data = {s: self.fetch_stock_data(s, period) for s in symbols}
        return {s: d for s, d in data.items() if d is not None}

    def fetch_company_info(self, symbol: str) -> Dict:
        index = zlib.crc32(symbol.encode())
        return {
            'symbol': symbol,
            'name': f'{symbol} (synthetic)',
            'sector': SECTORS[index % len(SECTORS)],
            'industry': 'Synthetic',
            'market_cap': 5e10,
        }

    def fetch_market_data(self) -> Dict[str, Dict]:
        if not self._data:
            return {}
        closes = pd.concat([d['Close'] / d['Close'].iloc[0] for d in self._data.values()], axis=1).mean(axis=1)
        price, prev = closes.iloc[-1] * 100, closes.iloc[-2] * 100
        return {'SPY': {'price': price, 'change_pct': (price / prev - 1) * 100, 'name': 'Synthetic market'}}

    def get_stock_news(self, symbol: str, num_articles: int = 5) -> List[Dict]:
        return []

    def clear_cache(self) -> None:
        pass
