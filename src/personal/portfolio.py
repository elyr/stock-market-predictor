"""
Your own portfolio: what you hold, how it did, and what needs attention.

Everything is derived from the list of transactions you record (buys and
sells), so the history is never lost and can be replayed:

- **Holdings** use the average-cost method: a buy adds to the quantity and the
  cost basis; a sell realises the gain on the shares sold at the average cost
  and keeps the average unchanged. Fees count as cost.
- **Performance over time** rebuilds the portfolio's value every day since
  the first trade from daily closes. It is compared with a **benchmark that
  received the same money on the same days** (the average asset of the
  universe, or Bitcoin for crypto). That is the honest "what if I had just
  bought the market" comparison, unaffected by when money went in or out.
- **Risk** is the portfolio's volatility from the assets' recent daily
  returns and their correlations, a likely range for next week's value, and
  plain-language warnings when your own rules are broken.

Nothing here uses future data: values on a date use closes up to that date.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

DEFAULT_RULES: Dict[str, Any] = {
    'max_position': 0.20,     # largest share of the portfolio in one asset
    'max_sector': 0.40,       # largest share in one sector (stocks)
    'max_volatility': 0.30,   # yearly volatility of the whole portfolio
    'min_positions': 5,       # fewer holdings than this is a concentrated bet
}

# z for a two-sided 90% interval of a normal distribution
Z90 = 1.645


@dataclass
class Holding:
    symbol: str
    quantity: float = 0.0
    cost_basis: float = 0.0       # what the current shares cost, fees included
    realized: float = 0.0         # gains already taken by selling
    fees: float = 0.0
    first_date: Optional[str] = None
    trades: int = 0

    @property
    def average_cost(self) -> Optional[float]:
        return self.cost_basis / self.quantity if self.quantity > 1e-12 else None


class TransactionError(ValueError):
    """A transaction that cannot be applied (for example selling more than you hold)."""


def apply_transactions(transactions: Iterable[Dict[str, Any]]) -> Dict[str, Holding]:
    """
    Holdings after a list of transactions, applied in date order.

    Each transaction has ``symbol``, ``side`` ('buy' or 'sell'), ``trade_date``,
    ``quantity`` (> 0), ``price`` (> 0) and optional ``fees``.

    Raises:
        TransactionError: a sale larger than the quantity held on that date
    """
    holdings: Dict[str, Holding] = {}
    ordered = sorted(transactions, key=lambda t: (t['trade_date'], t.get('created_at') or '', t.get('id') or ''))
    for t in ordered:
        h = holdings.setdefault(t['symbol'], Holding(t['symbol']))
        qty, price, fees = float(t['quantity']), float(t['price']), float(t.get('fees') or 0.0)
        h.fees += fees
        h.trades += 1
        h.first_date = h.first_date or t['trade_date']
        if t['side'] == 'buy':
            h.quantity += qty
            h.cost_basis += qty * price + fees
        elif t['side'] == 'sell':
            if qty > h.quantity + 1e-9:
                raise TransactionError(
                    f"Selling {qty:g} {t['symbol']} on {t['trade_date']}, but only {h.quantity:g} held then")
            average = h.cost_basis / h.quantity if h.quantity > 0 else 0.0
            h.realized += qty * (price - average) - fees
            h.cost_basis -= qty * average
            h.quantity -= qty
            if h.quantity < 1e-9:
                h.quantity, h.cost_basis = 0.0, 0.0
        else:
            raise TransactionError(f"Unknown side {t['side']!r}")
    return holdings


def value_history(transactions: List[Dict[str, Any]], closes: Dict[str, pd.Series],
                  benchmark: Optional[pd.Series] = None) -> pd.DataFrame:
    """
    The portfolio's value every day since the first trade, and a benchmark fed
    the same cash flows.

    Args:
        transactions: as for :func:`apply_transactions`
        closes: symbol -> daily closes
        benchmark: daily level of the comparison (e.g. the universe average
            rebased to 1); None skips the comparison

    Returns:
        DataFrame indexed by date with ``value`` (holdings at that close),
        ``invested`` (net money put in so far) and, with a benchmark,
        ``benchmark_value``
    """
    if not transactions:
        return pd.DataFrame(columns=['value', 'invested', 'benchmark_value'])
    start = pd.Timestamp(min(t['trade_date'] for t in transactions))
    series = {s: c.dropna().sort_index() for s, c in closes.items() if c is not None and len(c.dropna())}
    calendar = sorted({d for c in series.values() for d in c.index if d >= start})
    if not calendar:
        return pd.DataFrame(columns=['value', 'invested', 'benchmark_value'])
    calendar = pd.DatetimeIndex(calendar)
    prices = pd.DataFrame({s: c.reindex(calendar, method='ffill') for s, c in series.items()})

    # Cash flows on each calendar day (a trade on a non-trading day lands on the next session)
    flows = pd.Series(0.0, index=calendar)
    quantity_changes = pd.DataFrame(0.0, index=calendar, columns=prices.columns)
    for t in transactions:
        day = calendar[calendar.searchsorted(pd.Timestamp(t['trade_date']))] \
            if pd.Timestamp(t['trade_date']) <= calendar[-1] else None
        if day is None:
            continue
        amount = float(t['quantity']) * float(t['price'])
        fees = float(t.get('fees') or 0.0)
        sign = 1 if t['side'] == 'buy' else -1
        # Money in for a buy (price plus fees); money out for a sale (proceeds after fees)
        flows[day] += amount + fees if sign > 0 else -(amount - fees)
        if t['symbol'] in quantity_changes.columns:
            quantity_changes.loc[day, t['symbol']] += sign * float(t['quantity'])
    quantities = quantity_changes.cumsum()
    frame = pd.DataFrame({'value': (quantities * prices).sum(axis=1, min_count=1).fillna(0.0),
                          'invested': flows.cumsum()})
    if benchmark is not None and len(benchmark.dropna()):
        level = benchmark.dropna().sort_index().reindex(calendar, method='ffill').bfill()
        units = (flows / level).cumsum()  # every euro in or out buys or sells benchmark units that day
        frame['benchmark_value'] = units * level
    return frame


def portfolio_volatility(weights: Dict[str, float], closes: Dict[str, pd.Series], window: int = 120,
                         periods_per_year: int = 252) -> Optional[float]:
    """Yearly volatility of the current holdings, from recent daily returns and their correlations."""
    symbols = [s for s, w in weights.items() if w > 0 and s in closes]
    if not symbols:
        return None
    returns = pd.DataFrame({s: np.log(closes[s].dropna()).diff() for s in symbols}).dropna(how='all').tail(window)
    returns = returns.fillna(0.0)
    if len(returns) < 20:
        return None
    w = np.array([weights[s] for s in symbols])
    covariance = returns.cov().to_numpy() * periods_per_year
    return float(np.sqrt(max(w @ covariance @ w, 0.0)))


@dataclass
class Warning_:
    level: str      # 'high', 'medium' or 'info'
    kind: str
    message: str
    symbol: Optional[str] = None


def risk_warnings(positions: List[Dict[str, Any]], volatility: Optional[float],
                  rules: Dict[str, Any], sectors: bool = True) -> List[Dict[str, Any]]:
    """
    Plain-language warnings from your rules and the models' views.

    Args:
        positions: current holdings with ``symbol``, ``weight``, ``sector`` and
            optionally ``rank``, ``universe_size``, ``vol_up_probability``
        volatility: the portfolio's yearly volatility
        rules: see :data:`DEFAULT_RULES`
        sectors: check the sector limit (stocks)
    """
    found: List[Warning_] = []
    held = [p for p in positions if p['weight'] > 0]
    if not held:
        return []
    for p in sorted(held, key=lambda p: -p['weight']):
        if p['weight'] > rules['max_position']:
            found.append(Warning_('high', 'position',
                                  f"{p['symbol']} is {p['weight']:.0%} of your portfolio, above your "
                                  f"{rules['max_position']:.0%} limit. One bad week for it would hit the whole "
                                  f"portfolio; consider trimming it or adding other positions.", p['symbol']))
    if sectors:
        by_sector: Dict[str, float] = {}
        for p in held:
            if p.get('sector') and p['sector'] not in ('N/A', 'Other'):
                by_sector[p['sector']] = by_sector.get(p['sector'], 0.0) + p['weight']
        for sector, share in sorted(by_sector.items(), key=lambda kv: -kv[1]):
            if share > rules['max_sector']:
                found.append(Warning_('medium', 'sector',
                                      f"{share:.0%} of your portfolio is in {sector}, above your "
                                      f"{rules['max_sector']:.0%} limit. News that hits the whole sector would "
                                      f"move most of your money at once."))
    if volatility is not None and volatility > rules['max_volatility']:
        found.append(Warning_('medium', 'volatility',
                              f"Your portfolio swings about {volatility:.0%} a year, above your "
                              f"{rules['max_volatility']:.0%} limit. Calmer assets or smaller positions in the "
                              f"most volatile ones would bring it down."))
    if len(held) < rules['min_positions']:
        found.append(Warning_('medium', 'concentration',
                              f"Only {len(held)} {'position' if len(held) == 1 else 'positions'}. With fewer than "
                              f"{rules['min_positions']}, one asset's news moves your whole portfolio."))
    for p in held:
        if (p.get('vol_up_probability') or 0) >= 0.7:
            found.append(Warning_('info', 'volatility_rising',
                                  f"Swings in {p['symbol']} are likely to grow over the coming days "
                                  f"({p['vol_up_probability']:.0%} chance). Not a direction call: expect bigger moves "
                                  f"either way.", p['symbol']))
    for p in held:
        rank, size = p.get('rank'), p.get('universe_size')
        if rank and size and size >= 10 and rank > 0.8 * size:
            found.append(Warning_('info', 'model_low',
                                  f"The model ranks {p['symbol']} {rank} of {size}, in the bottom fifth for the "
                                  f"coming days. The evidence for such short-term calls is weak: treat it as a "
                                  f"reason to look, not as a sell signal.", p['symbol']))
    order = {'high': 0, 'medium': 1, 'info': 2}
    return [w.__dict__ for w in sorted(found, key=lambda w: order[w.level])]


def risk_label(volatility: Optional[float]) -> Optional[str]:
    """A word for the portfolio's yearly volatility."""
    if volatility is None:
        return None
    if volatility < 0.12:
        return 'Calm'
    if volatility < 0.22:
        return 'Moderate'
    if volatility < 0.40:
        return 'High'
    return 'Very high'


def weekly_range(value: float, volatility: Optional[float], days: int, periods_per_year: int) -> Optional[Dict[str, float]]:
    """Roughly 9 times in 10, the portfolio's value ``days`` ahead lies in this range (normal approximation)."""
    if volatility is None or value <= 0:
        return None
    scale = volatility * np.sqrt(days / periods_per_year)
    return {'low': float(value * np.exp(-Z90 * scale)), 'high': float(value * np.exp(Z90 * scale)), 'days': days}
