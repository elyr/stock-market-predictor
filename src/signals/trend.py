"""
The trend rule and the record that decides whether it may be offered.

The rule: hold an asset only while its price is above at least 2 of its 50-,
100- and 200-day averages. Research on real prices (``docs/research/``) found
that it does not predict returns, cuts returns by more than half on stocks, and
on coins keeps the return while cutting the worst fall. So Ledger offers it
only as *protection*, and only in a universe whose own history shows that.

* :func:`trend_state` is the rule. The state on day *t* uses closes up to *t*.
* :func:`rule_record` replays the rule on a universe's history: the position is
  taken one day after the state is known, with a cost on every change.
* :func:`trend_verdict` compares the record with the accuracy bar from
  ``signals.trend`` in config.yaml.
"""

from typing import Any, Dict, Optional, Tuple, Union

import pandas as pd

TREND_WINDOWS: Tuple[int, ...] = (50, 100, 200)
DAYS_PER_YEAR = 365.25

Prices = Union[pd.Series, pd.DataFrame]


def trend_state(close: Prices, windows: Tuple[int, ...] = TREND_WINDOWS) -> Prices:
    """
    1.0 while the close is above at least 2 of its moving averages, else 0.0.

    NaN until the longest average has enough closes. Only past and present
    closes enter, so a later price never changes an earlier state.
    """
    votes = sum((close > close.rolling(w).mean()).astype(float) for w in windows)
    return (votes >= 2).astype(float).where(close.rolling(max(windows)).mean().notna())


def _growth_stats(returns: pd.Series, years: float) -> Tuple[float, float]:
    """Return per year and worst drop (a positive fraction) of a daily return series."""
    equity = pd.concat([pd.Series([1.0]), (1 + returns).cumprod().reset_index(drop=True)], ignore_index=True)
    per_year = float(equity.iloc[-1] ** (1 / years) - 1)
    worst_drop = float(-(equity / equity.cummax() - 1).min())
    return per_year, worst_drop


def rule_record(closes: pd.DataFrame, cost_bps: float,
                windows: Tuple[int, ...] = TREND_WINDOWS) -> Optional[Dict[str, Any]]:
    """
    The rule's record on one universe's own history, against holding.

    Each day the portfolio is split equally among the assets that have a state.
    The state at the close of day *t* is acted on at the close of day *t+1*, so
    the position earns the return of day *t+2*. Every change of position costs
    ``cost_bps`` basis points of that asset.

    Returns ``None`` when no asset has a state yet. Drops are positive fractions
    (0.4 = a 40% fall from a peak).
    """
    state = trend_state(closes, windows)
    returns = closes.pct_change(fill_method=None)
    held = state.shift(2)
    valid = held.notna() & returns.notna()
    count = valid.sum(axis=1)
    held = held.where(valid)
    turnover = held.diff().abs().fillna(0.0)
    rule_each = (held * returns).fillna(0.0) - turnover * cost_bps / 1e4
    days = count > 0
    if not days.any():
        return None
    rule = (rule_each.where(valid).sum(axis=1) / count)[days]
    hold = (returns.where(valid).sum(axis=1) / count)[days]

    first, last = rule.index[0], rule.index[-1]
    start = closes.index[closes.index.get_loc(first) - 1]  # the close the first return starts from
    years = max((last - start).days / DAYS_PER_YEAR, 1 / DAYS_PER_YEAR)
    rule_year, rule_drop = _growth_stats(rule, years)
    hold_year, hold_drop = _growth_stats(hold, years)
    assets = int(valid.any().sum())
    return {
        'rule_return_per_year': rule_year, 'hold_return_per_year': hold_year,
        'rule_worst_drop': rule_drop, 'hold_worst_drop': hold_drop,
        'time_in_market': float((held == 1).sum().sum() / valid.sum().sum()),
        'trades_per_asset_per_year': float((turnover > 0).sum().sum() / assets / years),
        'first_date': str(first.date()), 'last_date': str(last.date()),
        'days': int(len(rule)), 'assets': assets, 'cost_bps': float(cost_bps),
    }


def trend_verdict(record: Optional[Dict[str, Any]], config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Whether the record meets the accuracy bar (``signals.trend`` in config.yaml).

    The universe passes only if the rule's worst drop is at least
    ``min_drop_improvement`` smaller than holding's *and* its return per year is
    at most ``max_return_shortfall`` below holding's, on at least
    ``min_history_days`` days of history.
    """
    if record is None:
        return {'passes': False, 'drop_improvement': None, 'return_shortfall': None,
                'reasons': ['There is not enough price history to test the rule.']}
    hold_drop = record['hold_worst_drop']
    improvement = (hold_drop - record['rule_worst_drop']) / hold_drop if hold_drop > 0 else 0.0
    shortfall = record['hold_return_per_year'] - record['rule_return_per_year']
    reasons = []
    if record['days'] < config['min_history_days']:
        reasons.append(f"Only {record['days']} days of history; at least {config['min_history_days']} are needed.")
    if improvement < config['min_drop_improvement']:
        reasons.append(f"The rule cut the worst drop by {improvement:.0%}; at least "
                       f"{config['min_drop_improvement']:.0%} is needed.")
    if shortfall > config['max_return_shortfall']:
        reasons.append(f"The rule returned {shortfall * 100:.1f} points a year less than holding; at most "
                       f"{config['max_return_shortfall'] * 100:.0f} points is allowed.")
    return {'passes': not reasons, 'drop_improvement': float(improvement), 'return_shortfall': float(shortfall),
            'reasons': reasons or ['The rule meets the bar in this universe\'s own history.']}


def state_summary(state: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """Each asset's latest state ('in' or 'out') and the date it last changed (None if it never has)."""
    out: Dict[str, Dict[str, Any]] = {}
    for symbol in state.columns:
        series = state[symbol].dropna()
        if series.empty:
            continue
        changes = series[series.diff().abs() > 0]
        out[symbol] = {'state': 'in' if series.iloc[-1] == 1 else 'out',
                       'last_change': str(changes.index[-1].date()) if len(changes) else None,
                       'as_of': str(series.index[-1].date())}
    return out


def trend_report(closes: pd.DataFrame, config: Dict[str, Any], universe: str) -> Dict[str, Any]:
    """The record, the verdict and every asset's state for one universe."""
    cost = config['cost_bps'][universe] if isinstance(config['cost_bps'], dict) else config['cost_bps']
    record = rule_record(closes, cost) if len(closes.columns) else None
    state = trend_state(closes) if len(closes.columns) else closes
    return {'record': record, 'verdict': trend_verdict(record, config), 'state': state,
            'assets': state_summary(state)}


def record_sentence(record: Dict[str, Any]) -> str:
    """The record in plain words, for alerts."""
    return (f"Since {record['first_date']}, in this universe, following the rule returned "
            f"{record['rule_return_per_year'] * 100:.1f}% a year with a worst drop of "
            f"{record['rule_worst_drop'] * 100:.0f}%; holding returned "
            f"{record['hold_return_per_year'] * 100:.1f}% a year with a worst drop of "
            f"{record['hold_worst_drop'] * 100:.0f}%.")


def trend_changes(state: pd.DataFrame, date: pd.Timestamp) -> Dict[str, float]:
    """Assets whose state on ``date`` differs from the bar before it: symbol -> new state (1.0 or 0.0)."""
    if date not in state.index:
        return {}
    pos = state.index.get_loc(date)
    if pos == 0:
        return {}
    now, before = state.iloc[pos], state.iloc[pos - 1]
    flipped = now.notna() & before.notna() & (now != before)
    return {s: float(now[s]) for s in state.columns[flipped.values]}


__all__ = ['TREND_WINDOWS', 'rule_record', 'trend_state', 'trend_verdict', 'trend_report', 'trend_changes',
           'state_summary', 'record_sentence']
