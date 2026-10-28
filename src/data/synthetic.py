"""
Synthetic market data for offline demos and tests.

Prices follow a one-factor model: each asset's daily return is a shared market
return times the asset's beta, plus idiosyncratic noise. Both the market and the
idiosyncratic parts have GARCH(1,1) volatility, so calm and turbulent periods
cluster the way they do in real markets.

Optionally a known, learnable signal is planted (short-term mean reversion:
tomorrow's idiosyncratic return leans against today's) so tests can check that
the models and the backtest find real edge, and find none when there is none.

Symbols ending in ``-USD`` are generated as crypto: a 7-day calendar, higher
volatility and a market factor that the Bitcoin series itself follows.

Nothing here is real market data.
"""

import zlib
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

SECTORS = ['Technology', 'Healthcare', 'Financial Services', 'Consumer Cyclical',
           'Industrials', 'Energy', 'Consumer Defensive', 'Utilities']

PERIOD_DAYS = {'5d': 5, '1mo': 21, '3mo': 63, '6mo': 126, '1y': 252, '2y': 504, '3y': 756, '5y': 1260}


def is_crypto(symbol: str) -> bool:
    return symbol.upper().endswith('-USD')


def _garch_path(rng: np.random.Generator, days: int, vol: float,
                alpha: float = 0.10, beta: float = 0.85) -> np.ndarray:
    """Daily shocks with GARCH(1,1) volatility around a long-run level ``vol``."""
    omega = vol ** 2 * (1 - alpha - beta)
    z = rng.standard_normal(days)
    eps = np.empty(days)
    var = vol ** 2
    for t in range(days):
        eps[t] = np.sqrt(var) * z[t]
        var = omega + alpha * eps[t] ** 2 + beta * var
    return eps


def generate_market(symbols: List[str], days: int = 504, seed: int = 42,
                    reversal: float = 0.0, end: str = '2026-10-27',
                    crypto: Optional[bool] = None) -> Dict[str, pd.DataFrame]:
    """
    Generate daily OHLCV data for several assets on a shared calendar.

    Args:
        symbols: Ticker names to generate
        days: Number of trading days (calendar days for crypto)
        seed: Random seed (same seed gives identical data)
        reversal: Strength of the planted mean-reversion signal. 0 means returns
            are unpredictable; 0.3 means about 30% of each day's idiosyncratic
            move reverses the next day.
        end: Last date in the series
        crypto: Generate crypto-style data; inferred from the symbols when None

    Returns:
        Dictionary of symbol -> DataFrame with Open, High, Low, Close, Volume, Symbol
    """
    if crypto is None:
        crypto = bool(symbols) and all(is_crypto(s) for s in symbols)
    dates = pd.date_range(end=end, periods=days, freq='D') if crypto else pd.bdate_range(end=end, periods=days)
    market_rng = np.random.default_rng([seed, 1 if crypto else 0])
    market = (0.0008 if crypto else 0.0004) + _garch_path(market_rng, days, 0.035 if crypto else 0.01)

    result = {}
    for symbol in symbols:
        # Each symbol's own stream: same symbol + seed always gives the same series
        rng = np.random.default_rng([seed, zlib.crc32(symbol.encode())])
        is_btc = symbol.upper() == 'BTC-USD'
        beta = 1.0 if is_btc else rng.uniform(0.7, 1.5) if crypto else rng.uniform(0.6, 1.4)
        vol = (0.008 if is_btc else rng.uniform(0.02, 0.05)) if crypto else rng.uniform(0.012, 0.025)
        noise = _garch_path(rng, days, vol)
        idio = np.zeros(days)
        for t in range(days):
            idio[t] = noise[t] - (reversal * idio[t - 1] if t > 0 else 0.0)
        returns = np.clip(beta * market + idio, -0.45, 0.45)

        start_price = float(np.exp(rng.uniform(np.log(0.1), np.log(60000)))) if crypto else rng.uniform(20, 400)
        close = start_price * np.exp(np.cumsum(returns))
        intraday = np.abs(returns) + vol / 2
        open_ = close / np.exp(returns) * np.exp(rng.normal(0, vol / 4, days))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, intraday / 2)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, intraday / 2)))
        base_volume = rng.uniform(5e7, 5e9) if crypto else rng.uniform(2e6, 3e7)
        volume = base_volume * np.exp(rng.normal(0, 0.3, days) + 8 * np.abs(returns))

        result[symbol] = pd.DataFrame({
            'Open': open_, 'High': high, 'Low': low, 'Close': close,
            'Volume': volume.round(), 'Symbol': symbol,
        }, index=dates)
    return result


class SyntheticDataCollector:
    """
    Drop-in stand-in for :class:`DataCollector` serving synthetic data.

    Supports the methods the pipelines, sentiment analyzer and backtester call.
    News is empty and market data is derived from the synthetic assets.
    """

    # Index/ETF tickers the sentiment module asks for; synthetic mode has no such data
    NON_STOCK_SYMBOLS = {'SPY', 'QQQ', 'DIA', 'GLD', 'TLT', 'XLK', 'XLV', 'XLF', 'XLY', 'XLC',
                         'XLI', 'XLP', 'XLE', 'XLU', 'XLRE', 'XLB'}

    def __init__(self, symbols: Optional[List[str]] = None, days: int = 504,
                 seed: int = 42, reversal: float = 0.0):
        self.days = days
        self.seed = seed
        self.reversal = reversal
        self._data: Dict[str, pd.DataFrame] = {}
        if symbols:
            self._ensure(symbols)

    def _ensure(self, symbols: List[str]) -> None:
        missing = [s for s in symbols if s not in self._data]
        for crypto in (False, True):
            group = [s for s in missing if is_crypto(s) == crypto]
            if group:
                days = int(self.days * 365 / 252) if crypto else self.days
                self._data.update(generate_market(group, days, self.seed, self.reversal, crypto=crypto))

    def fetch_stock_data(self, symbol: str, period: str = '2y') -> Optional[pd.DataFrame]:
        if symbol.startswith('^') or symbol in self.NON_STOCK_SYMBOLS:
            return None
        self._ensure([symbol])
        rows = PERIOD_DAYS.get(period, self.days)
        if is_crypto(symbol):
            rows = int(rows * 365 / 252)
        return self._data[symbol].tail(rows).copy()

    def fetch_multiple_stocks(self, symbols: List[str], period: str = '2y') -> Dict[str, pd.DataFrame]:
        data = {s: self.fetch_stock_data(s, period) for s in symbols}
        return {s: d for s, d in data.items() if d is not None}

    def fetch_company_info(self, symbol: str) -> Dict:
        if is_crypto(symbol):
            return {'symbol': symbol, 'name': f'{symbol} (synthetic)', 'sector': None, 'market_cap': 5e10}
        index = zlib.crc32(symbol.encode())
        return {
            'symbol': symbol,
            'name': f'{symbol} (synthetic)',
            'sector': SECTORS[index % len(SECTORS)],
            'industry': 'Synthetic',
            'market_cap': 5e10,
        }

    def fetch_market_data(self) -> Dict[str, Dict]:
        stocks = [d for s, d in self._data.items() if not is_crypto(s)]
        if not stocks:
            return {}
        closes = pd.concat([d['Close'] / d['Close'].iloc[0] for d in stocks], axis=1).mean(axis=1)
        price, prev = closes.iloc[-1] * 100, closes.iloc[-2] * 100
        return {'SPY': {'price': price, 'change_pct': (price / prev - 1) * 100, 'name': 'Synthetic market'}}

    def get_stock_news(self, symbol: str, num_articles: int = 5) -> List[Dict]:
        return []

    def clear_cache(self) -> None:
        pass
