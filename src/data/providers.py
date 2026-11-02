"""
Fallback price sources, used when Yahoo Finance fails for a symbol.

Yahoo Finance is free and unofficial: it sometimes throttles or blocks
requests, more often from cloud servers than from home. When it fails after
its retries, the collector asks these providers in order:

- **Coinbase** (crypto, ``*-USD``): the exchange's public daily candles. No
  key needed. Up to 300 days per request, so longer histories are paged.
- **Alpha Vantage** (stocks): daily prices with a free API key in
  ``ALPHA_VANTAGE_API_KEY``. The free tier allows about 25 requests a day, so it
  covers a few symbols, not a whole universe.

Every provider returns the same frame as Yahoo Finance (``Open``, ``High``,
``Low``, ``Close``, ``Volume``, ``Symbol`` on a timezone-free daily index) and
records where each series came from, so the app can say so.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

PERIOD_DAYS = {'1d': 1, '5d': 5, '1mo': 31, '3mo': 92, '6mo': 183, '1y': 366, '2y': 731, '3y': 1096,
               '5y': 1827, '10y': 3653, 'max': 3653}


def period_days(period: str) -> int:
    return PERIOD_DAYS.get(period, 366)


def _frame(rows: List[Dict], symbol: str) -> Optional[pd.DataFrame]:
    if not rows:
        return None
    df = pd.DataFrame(rows).drop_duplicates('Date').set_index('Date').sort_index()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
    df['Symbol'] = symbol
    return df


class Provider:
    """A source of daily prices for some symbols."""

    name = 'provider'

    def supports(self, symbol: str) -> bool:
        raise NotImplementedError

    def fetch(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        raise NotImplementedError


class CoinbaseProvider(Provider):
    """Coinbase Exchange public daily candles (no key)."""

    name = 'Coinbase'
    url = 'https://api.exchange.coinbase.com/products/{product}/candles'
    page_days = 300

    def __init__(self, get: Optional[Callable] = None, timeout: float = 15):
        import requests
        self.get = get or requests.get
        self.timeout = timeout

    def supports(self, symbol: str) -> bool:
        return symbol.upper().endswith('-USD')

    def fetch(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start_limit = end - timedelta(days=period_days(period))
        rows: List[Dict] = []
        while end > start_limit:
            start = max(start_limit, end - timedelta(days=self.page_days))
            response = self.get(self.url.format(product=symbol.upper()), timeout=self.timeout,
                                params={'granularity': 86400, 'start': start.isoformat(), 'end': end.isoformat()},
                                headers={'User-Agent': 'ledger-research-app'})
            response.raise_for_status()
            candles = response.json()
            if not candles:
                break
            # [time, low, high, open, close, volume], newest first
            rows += [{'Date': datetime.fromtimestamp(c[0], timezone.utc), 'Low': c[1], 'High': c[2], 'Open': c[3],
                      'Close': c[4], 'Volume': c[5]} for c in candles]
            end = start
        return _frame(rows, symbol)


class AlphaVantageProvider(Provider):
    """Alpha Vantage daily prices (needs ALPHA_VANTAGE_API_KEY)."""

    name = 'Alpha Vantage'
    url = 'https://www.alphavantage.co/query'

    def __init__(self, key: Optional[str] = None, get: Optional[Callable] = None, timeout: float = 20):
        import requests
        self.key = key if key is not None else os.getenv('ALPHA_VANTAGE_API_KEY', '')
        self.get = get or requests.get
        self.timeout = timeout

    def supports(self, symbol: str) -> bool:
        return bool(self.key) and not symbol.upper().endswith('-USD') and not symbol.startswith('^')

    def fetch(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        # 'compact' is the last ~100 sessions and works on the free tier; longer needs 'full'
        size = 'compact' if period_days(period) <= 140 else 'full'
        response = self.get(self.url, timeout=self.timeout, params={
            'function': 'TIME_SERIES_DAILY', 'symbol': symbol.upper(), 'outputsize': size, 'apikey': self.key})
        response.raise_for_status()
        payload = response.json()
        series = payload.get('Time Series (Daily)')
        if not series:
            # Rate limit or premium-only message: say why, without the key
            note = payload.get('Note') or payload.get('Information') or payload.get('Error Message') or 'no data'
            raise RuntimeError(f'Alpha Vantage: {str(note)[:160]}')
        cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=period_days(period))
        rows = [{'Date': day, 'Open': v['1. open'], 'High': v['2. high'], 'Low': v['3. low'], 'Close': v['4. close'],
                 'Volume': v['5. volume']} for day, v in series.items() if pd.Timestamp(day) >= cutoff]
        return _frame(rows, symbol)


def default_providers() -> List[Provider]:
    """The fallbacks available here: Coinbase always, Alpha Vantage when a key is set."""
    providers: List[Provider] = [CoinbaseProvider()]
    if os.getenv('ALPHA_VANTAGE_API_KEY'):
        providers.append(AlphaVantageProvider())
    return providers
