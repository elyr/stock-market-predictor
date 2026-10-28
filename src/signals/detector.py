"""
Market signal detection.

The detector does not predict anything. It looks at the latest price bar of
every asset and flags what is *unusual compared with that asset's own history*,
so a 3% move in a sleepy utility stock and a 3% move in a volatile coin are
judged differently:

* **Unusual move:** today's return minus the universe's average return, measured
  in standard deviations of that same difference over the previous 60 bars.
  Removing the universe average means a market-wide drop does not produce one
  alert per asset; the market-wide drop gets its own alert instead.
* **Volume spike:** volume several times its 20-bar average (close scan only,
  since volume is incomplete at the open).
* **Gap:** the open far from the previous close, in standard deviations and in
  percent.
* **Market-wide move:** the universe's average return, in standard deviations of
  its own history; and broad selloffs where almost every asset is down.

After an analysis, :func:`detect_from_analysis` adds portfolio changes and
holdings whose volatility forecast is turning up.

Scans run twice a day: just after the US open (``session='open'``: gaps and
early moves) and just after the close (``session='close'``: everything).
"""

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

SEVERITY_ORDER = {'info': 0, 'warning': 1, 'critical': 2}

DEFAULT_SIGNAL_CONFIG: Dict[str, Any] = {
    'enabled': True,
    'history_days': 60,
    'cooldown_hours': 12,
    'schedule': {
        'timezone': 'America/New_York',
        'open': '09:45',   # after the US open, once opening prices settle
        'close': '16:15',  # after the US close
        'stocks_weekdays_only': True,
    },
    'thresholds': {
        'move_z': 3.0,
        'move_z_critical': 5.0,
        'volume_ratio': 3.0,
        'volume_ratio_critical': 5.0,
        'gap_z': 3.0,
        'gap_min_pct': {'stocks': 0.02, 'crypto': 0.04},
        'market_z': 3.0,
        'market_z_critical': 4.0,
        'breadth_share': 0.85,
        'vol_up_probability': 0.7,
        'vol_increase_ratio': 1.2,
    },
}


def merge_signal_config(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge the ``signals`` section of config.yaml over the defaults."""
    merged = copy.deepcopy(DEFAULT_SIGNAL_CONFIG)
    for key, value in (user or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


@dataclass
class Signal:
    """One detected event, ready to become a notification."""

    type: str
    severity: str
    title: str
    body: str
    event_date: str
    symbol: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)

    def dedupe_key(self, universe: str) -> str:
        """The same event on the same day is only ever stored once."""
        return f"{universe}:{self.type}:{self.symbol or '*'}:{self.event_date}"

    def to_dict(self) -> Dict[str, Any]:
        return {'type': self.type, 'severity': self.severity, 'title': self.title, 'body': self.body,
                'event_date': self.event_date, 'symbol': self.symbol, 'data': self.data}


def _fmt_pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


class SignalDetector:
    """
    Detects unusual events in one universe's price data.

    Args:
        universe: 'stocks' or 'crypto' (sets the minimum gap size)
        config: the ``signals`` section of config.yaml (merged over defaults)
    """

    def __init__(self, universe: str = 'stocks', config: Optional[Dict[str, Any]] = None):
        self.universe = universe
        self.config = merge_signal_config(config)
        self.t = self.config['thresholds']
        self.history = int(self.config['history_days'])

    def scan(self, raw: Dict[str, pd.DataFrame], session: str = 'close', lookback: int = 1,
             names: Optional[Dict[str, str]] = None, holdings: Iterable[str] = ()) -> List[Signal]:
        """
        Check the last ``lookback`` bars of every asset.

        Args:
            raw: symbol -> OHLCV DataFrame (daily bars, oldest first)
            session: 'open' checks gaps and early moves; 'close' checks everything
            lookback: how many recent bars to check (1 for a live scan)
            names: optional symbol -> display name
            holdings: symbols in the current suggested portfolio (mentioned in alerts)
        """
        names = names or {}
        holdings = set(holdings)
        closes = pd.concat({s: d['Close'] for s, d in raw.items() if d is not None and len(d) > 2}, axis=1)
        if closes.empty:
            return []
        returns = closes.pct_change(fill_method=None)
        market = returns.mean(axis=1)
        dates = closes.index[-lookback:]

        signals: List[Signal] = []
        for date in dates:
            signals += self._market_signals(returns, market, date)
            for symbol, data in raw.items():
                if data is None or date not in data.index:
                    continue
                signals += self._asset_signals(symbol, data, returns[symbol], market, date, session,
                                               names.get(symbol, symbol), symbol in holdings)
        order = {'critical': 0, 'warning': 1, 'info': 2}
        return sorted(signals, key=lambda s: (s.event_date, order[s.severity]), reverse=False)

    # --------------------------------------------------------------- assets

    def _asset_signals(self, symbol: str, data: pd.DataFrame, returns: pd.Series, market: pd.Series,
                       date: pd.Timestamp, session: str, name: str, held: bool) -> List[Signal]:
        pos = data.index.get_loc(date)
        if pos < 21:
            return []
        start = max(1, pos - self.history)
        excess = (returns - market).reindex(data.index)
        past_excess = excess.iloc[start:pos].dropna()
        past_returns = returns.reindex(data.index).iloc[start:pos].dropna()
        if len(past_excess) < 20 or past_excess.std() == 0 or past_returns.std() == 0:
            return []

        day = str(date.date())
        ret = float(returns.loc[date]) if pd.notna(returns.loc[date]) else 0.0
        market_ret = float(market.loc[date]) if pd.notna(market.loc[date]) else 0.0
        z = (ret - market_ret) / past_excess.std()
        holding_note = ' It is in your current portfolio.' if held else ''
        signals = []

        volume_ratio = None
        if session == 'close':
            past_volume = data['Volume'].iloc[max(0, pos - 20):pos]
            if past_volume.mean() > 0:
                volume_ratio = float(data['Volume'].iloc[pos] / past_volume.mean())

        if abs(z) >= self.t['move_z']:
            direction = 'up' if ret > 0 else 'down'
            when = 'so far today' if session == 'open' else 'today'
            volume_note = f" on {volume_ratio:.1f}x its usual volume" if volume_ratio and volume_ratio >= 2 else ''
            severity = 'critical' if abs(z) >= self.t['move_z_critical'] else 'warning'
            signals.append(Signal(
                type='unusual_move', severity=severity, symbol=symbol, event_date=day,
                title=f"{symbol} {direction} {abs(ret) * 100:.1f}% {when}",
                body=(f"{name} moved {_fmt_pct(ret)} {when}{volume_note}, against {_fmt_pct(market_ret)} for the "
                      f"average {'coin' if self.universe == 'crypto' else 'stock'}. That is a "
                      f"{abs(z):.1f}-standard-deviation move for this asset.{holding_note}"),
                data={'return': ret, 'market_return': market_ret, 'z': float(z), 'volume_ratio': volume_ratio,
                      'held': held, 'session': session},
            ))
        elif volume_ratio is not None and volume_ratio >= self.t['volume_ratio']:
            severity = 'critical' if volume_ratio >= self.t['volume_ratio_critical'] else 'warning'
            signals.append(Signal(
                type='volume_spike', severity=severity, symbol=symbol, event_date=day,
                title=f"{symbol} traded {volume_ratio:.1f}x its usual volume",
                body=(f"{name} traded {volume_ratio:.1f} times its 20-day average volume while the price moved "
                      f"{_fmt_pct(ret)}. Heavy volume without a big move often comes before news or a breakout."
                      f"{holding_note}"),
                data={'return': ret, 'volume_ratio': volume_ratio, 'held': held, 'session': session},
            ))

        prev_close = data['Close'].iloc[pos - 1]
        gap = float(data['Open'].iloc[pos] / prev_close - 1) if prev_close else 0.0
        gap_z = gap / past_returns.std()
        min_gap = self.t['gap_min_pct'].get(self.universe, 0.02) if isinstance(self.t['gap_min_pct'], dict) \
            else self.t['gap_min_pct']
        if abs(gap_z) >= self.t['gap_z'] and abs(gap) >= min_gap:
            severity = 'critical' if abs(gap_z) >= self.t['move_z_critical'] else 'warning'
            signals.append(Signal(
                type='gap', severity=severity, symbol=symbol, event_date=day,
                title=f"{symbol} opened {abs(gap) * 100:.1f}% {'higher' if gap > 0 else 'lower'}",
                body=(f"{name} opened {'above' if gap > 0 else 'below'} the previous close by {abs(gap) * 100:.1f}%, "
                      f"a {abs(gap_z):.1f}-standard-deviation gap. Gaps this size usually follow overnight news."
                      f"{holding_note}"),
                data={'gap': gap, 'z': float(gap_z), 'held': held, 'session': session},
            ))
        return signals

    # --------------------------------------------------------------- market

    def _market_signals(self, returns: pd.DataFrame, market: pd.Series, date: pd.Timestamp) -> List[Signal]:
        pos = market.index.get_loc(date)
        past = market.iloc[max(1, pos - self.history):pos].dropna()
        if len(past) < 20 or past.std() == 0 or pd.isna(market.loc[date]):
            return []
        day = str(date.date())
        move = float(market.loc[date])
        z = move / past.std()
        today = returns.loc[date].dropna()
        down_share = float((today < 0).mean()) if len(today) else 0.0
        what = 'coins' if self.universe == 'crypto' else 'stocks'
        signals = []

        if abs(z) >= self.t['market_z']:
            severity = 'critical' if abs(z) >= self.t['market_z_critical'] else 'warning'
            direction = 'rally' if move > 0 else 'selloff'
            signals.append(Signal(
                type='market_move', severity=severity, event_date=day,
                title=f"Market-wide {direction}: average {what[:-1]} {'up' if move > 0 else 'down'} {abs(move) * 100:.1f}%",
                body=(f"The average {what[:-1]} in this universe moved {_fmt_pct(move)}, a {abs(z):.1f}-standard-"
                      f"deviation day. {down_share:.0%} of {what} fell. Moves like this usually reflect news that "
                      f"affects the whole market rather than any single asset."),
                data={'return': move, 'z': float(z), 'down_share': down_share, 'assets': int(len(today))},
            ))
        elif down_share >= self.t['breadth_share'] and z <= -1.5 and len(today) >= 5:
            signals.append(Signal(
                type='market_move', severity='warning', event_date=day,
                title=f"Broad selloff: {down_share:.0%} of {what} down",
                body=(f"{down_share:.0%} of {what} fell, with the average down {_fmt_pct(move)}. The move is not "
                      f"extreme in size, but its breadth is unusual."),
                data={'return': move, 'z': float(z), 'down_share': down_share, 'assets': int(len(today))},
            ))
        return signals


def detect_from_analysis(universe: str, current: List[Dict[str, Any]], previous_picks: Optional[List[str]],
                         event_date: str, config: Optional[Dict[str, Any]] = None) -> List[Signal]:
    """
    Signals that follow from a new analysis.

    Args:
        universe: 'stocks' or 'crypto'
        current: the new run's rankings (API row dicts with symbol, picked, vol_* fields)
        previous_picks: symbols picked in the previous live run (None if there was none)
        event_date: the new run's price date
    """
    t = merge_signal_config(config)['thresholds']
    picks = [r for r in current if r.get('picked')]
    signals: List[Signal] = []

    if previous_picks is not None:
        now = [r['symbol'] for r in picks]
        added = [s for s in now if s not in previous_picks]
        removed = [s for s in previous_picks if s not in now]
        if added or removed:
            parts = []
            if added:
                parts.append(f"added {', '.join(added)}")
            if removed:
                parts.append(f"dropped {', '.join(removed)}")
            signals.append(Signal(
                type='portfolio_change', severity='info', event_date=event_date,
                title=f"Portfolio updated: {len(added)} in, {len(removed)} out",
                body=f"The latest analysis {' and '.join(parts)}.",
                data={'added': added, 'removed': removed},
            ))

    for row in picks:
        probability, current_vol, forecast = row.get('vol_up_probability'), row.get('volatility'), row.get('vol_forecast')
        if None in (probability, current_vol, forecast) or not current_vol:
            continue
        if probability >= t['vol_up_probability'] and forecast / current_vol >= t['vol_increase_ratio']:
            signals.append(Signal(
                type='volatility_rising', severity='info', symbol=row['symbol'], event_date=event_date,
                title=f"{row['symbol']}: bigger swings expected",
                body=(f"The volatility model gives a {probability:.0%} chance that {row.get('company_name', row['symbol'])} "
                      f"gets more volatile, forecasting {forecast:.0%} a year against {current_vol:.0%} now. "
                      f"It is in your current portfolio; consider a smaller position."),
                data={'probability': probability, 'current': current_vol, 'forecast': forecast},
            ))
    return signals
