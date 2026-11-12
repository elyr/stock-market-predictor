"""
Tests for the trend rule, its record and the protection alerts. Offline, on small
hand-made and synthetic prices.
"""

import numpy as np
import pandas as pd
import pytest

from src.signals import SignalDetector
from src.signals.trend import rule_record, trend_state, trend_verdict

PASSING = {'trend': {'min_history_days': 10, 'min_drop_improvement': -1.0, 'max_return_shortfall': 1e6}}
TREND_TYPES = ('trend_exit', 'trend_enter')


def ohlcv(close: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({'Open': close, 'High': close, 'Low': close, 'Close': close, 'Volume': 1e6})


def v_shape(up_days=260, drop=0.7, recovery=0.0, recovery_days=0, down_days=60) -> pd.Series:
    """Steady climb, a sudden fall, then a slow slide (or a recovery)."""
    prices = [100 * 1.002 ** i for i in range(up_days)]
    prices.append(prices[-1] * drop)
    for _ in range(down_days):
        prices.append(prices[-1] * 0.999)
    for _ in range(recovery_days):
        prices.append(prices[-1] * (1 + recovery))
    return pd.Series(prices, index=pd.bdate_range('2020-01-01', periods=len(prices)))


def trend_alerts(close: pd.Series, config=None, **scan_args):
    detector = SignalDetector('stocks', config)
    signals = detector.scan({'AAA': ohlcv(close)}, lookback=len(close), names={'AAA': 'Alpha Corp'}, **scan_args)
    return [s for s in signals if s.type in TREND_TYPES]


def test_state_is_one_when_above_two_of_three_averages():
    close = v_shape()
    state = trend_state(close)
    assert state.iloc[:199].isna().all()                 # needs 200 closes
    assert state.iloc[199:260].eq(1.0).all()             # a steady climb is above every average
    assert state.iloc[260:].eq(0.0).all()                # after the fall it is below all three


def test_state_never_uses_later_prices():
    rng = np.random.default_rng(0)
    close = pd.Series(100 * np.exp(rng.normal(0, 0.02, 500).cumsum()), index=pd.bdate_range('2020-01-01', periods=500))
    changed = close.copy()
    changed.iloc[300:] *= rng.uniform(0.5, 2.0, 200)     # rewrite the future after day 299
    pd.testing.assert_series_equal(trend_state(close).iloc[:300], trend_state(changed).iloc[:300])


def test_record_matches_a_hand_computed_case():
    # Windows (2, 2, 2) make the state "closed up today". One asset, calendar days.
    close = pd.DataFrame({'A': [100, 102, 101, 103, 104, 100.0]},
                         index=pd.date_range('2024-01-01', periods=6))
    # state by day: -, up, down, up, up, down.  Acted on a day later, held over the return two days on:
    # day 3 (state of day 1: in), day 4 (day 2: out), day 5 (day 3: in)
    r3, r4, r5 = 103 / 101 - 1, 104 / 103 - 1, 100 / 104 - 1
    cost = 0.01                                          # 100 bps on each change (days 4 and 5)
    rule = [r3, -cost, r5 - cost]
    hold = [r3, r4, r5]
    record = rule_record(close, cost_bps=100, windows=(2, 2, 2))

    years = 3 / 365.25                                   # from the close of day 2 to the close of day 5
    rule_growth, hold_growth = np.prod([1 + x for x in rule]), np.prod([1 + x for x in hold])
    assert record['rule_return_per_year'] == pytest.approx(rule_growth ** (1 / years) - 1)
    assert record['hold_return_per_year'] == pytest.approx(hold_growth ** (1 / years) - 1)
    rule_equity, hold_equity = np.cumprod([1 + x for x in rule]), np.cumprod([1 + x for x in hold])
    assert record['rule_worst_drop'] == pytest.approx(1 - rule_equity[2] / rule_equity[0])
    assert record['hold_worst_drop'] == pytest.approx(1 - hold_equity[2] / hold_equity[1])  # the peak is day 4
    assert record['time_in_market'] == pytest.approx(2 / 3)
    assert record['trades_per_asset_per_year'] == pytest.approx(2 / years)
    assert (record['first_date'], record['last_date'], record['days'], record['assets']) == \
           ('2024-01-04', '2024-01-06', 3, 1)


def test_verdict_needs_history_a_smaller_drop_and_a_small_return_shortfall():
    config = {'min_history_days': 750, 'min_drop_improvement': 0.25, 'max_return_shortfall': 0.02}
    good = {'days': 1000, 'rule_worst_drop': 0.3, 'hold_worst_drop': 0.6,
            'rule_return_per_year': 0.2, 'hold_return_per_year': 0.21}
    assert trend_verdict(good, config)['passes']
    assert not trend_verdict({**good, 'days': 500}, config)['passes']
    assert not trend_verdict({**good, 'rule_worst_drop': 0.5}, config)['passes']
    assert not trend_verdict({**good, 'rule_return_per_year': 0.1}, config)['passes']
    assert not trend_verdict(None, config)['passes']


def test_one_state_flip_gives_exactly_one_alert():
    alerts = trend_alerts(v_shape(), PASSING)
    assert len(alerts) == 1
    alert = alerts[0]
    assert (alert.type, alert.severity, alert.symbol) == ('trend_exit', 'warning', 'AAA')
    assert alert.title == 'Alpha Corp: move to cash (protection)'
    assert 'a year with a worst drop of' in alert.body and 'Since 20' in alert.body
    assert alert.body.endswith('This rule limits deep falls. It does not predict returns.')
    assert alert.event_date == str(v_shape().index[260].date())  # the first bar below the averages


def test_coming_back_up_gives_a_second_alert_of_type_enter():
    alerts = trend_alerts(v_shape(drop=0.8, down_days=10, recovery=0.015, recovery_days=80), PASSING)
    assert [a.type for a in alerts] == ['trend_exit', 'trend_enter']
    assert alerts[1].severity == 'info' and alerts[1].title == 'Alpha Corp: trend is back up'


def test_no_alert_when_the_universe_fails_the_bar():
    # Default bar needs 750 days of history; this universe has about 320
    assert trend_alerts(v_shape()) == []
    strict = {'trend': {'min_history_days': 10, 'min_drop_improvement': 0.99, 'max_return_shortfall': 0.0}}
    assert trend_alerts(v_shape(), strict) == []


def test_no_trend_alert_at_the_open_scan():
    assert trend_alerts(v_shape(), PASSING, session='open') == []


def test_no_trend_alert_when_turned_off():
    assert trend_alerts(v_shape(), {**PASSING, 'trend': {**PASSING['trend'], 'enabled': False}}) == []


def test_record_is_computed_once_per_set_of_prices():
    detector = SignalDetector('stocks', PASSING)
    closes = pd.DataFrame({'AAA': v_shape()})
    assert detector.trend_report(closes) is detector.trend_report(closes)
