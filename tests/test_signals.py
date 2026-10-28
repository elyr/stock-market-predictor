"""
Tests for market signal detection, notification rules and the scan schedule.
"""

from datetime import datetime, timezone

import pytest

from api.notifications import Notifier, scan_times
from api.store import NotificationStore, Store
from src.data.synthetic import generate_market
from src.signals import SignalDetector, detect_from_analysis

SYMBOLS = [f"SG{chr(65 + i)}" for i in range(20)]


@pytest.fixture
def market():
    # Seed 3 ends on a calm day, so each test sees only the event it plants
    return generate_market(SYMBOLS, days=200, seed=3)


def shock(data, close=1.0, open_=1.0, volume=1.0):
    data = data.copy()
    last = data.index[-1]
    data.loc[last, 'Close'] *= close
    data.loc[last, 'Open'] *= open_
    data.loc[last, 'Volume'] *= volume
    data.loc[last, 'High'] = data.loc[last, ['Open', 'Close', 'High']].max()
    data.loc[last, 'Low'] = data.loc[last, ['Open', 'Close', 'Low']].min()
    return data


def test_quiet_market_gives_no_alerts(market):
    assert SignalDetector('stocks').scan(market) == []


def test_crash_on_heavy_volume_is_critical_and_mentions_the_holding(market):
    market['SGD'] = shock(market['SGD'], close=0.85, volume=6)
    signals = SignalDetector('stocks').scan(market, holdings=['SGD'], names={'SGD': 'Test Corp'})
    move = next(s for s in signals if s.type == 'unusual_move')
    assert move.symbol == 'SGD' and move.severity == 'critical'
    assert 'down' in move.title and '-' not in move.title.split('down')[1][:3]
    assert 'Test Corp' in move.body and 'usual volume' in move.body and 'your current portfolio' in move.body
    assert not any(s.type == 'volume_spike' and s.symbol == 'SGD' for s in signals)  # folded into the move alert


def test_volume_spike_without_a_big_move(market):
    market['SGB'] = shock(market['SGB'], volume=4)
    signals = SignalDetector('stocks').scan(market)
    assert [(s.type, s.symbol) for s in signals] == [('volume_spike', 'SGB')]


def test_gap_detected_at_the_open_and_volume_ignored(market):
    market['SGC'] = shock(market['SGC'], open_=0.9, volume=8)
    signals = SignalDetector('stocks').scan(market, session='open')
    assert any(s.type == 'gap' and s.symbol == 'SGC' and 'lower' in s.title for s in signals)
    assert not any(s.type == 'volume_spike' for s in signals)


def test_market_wide_drop_gives_one_alert_not_twenty(market):
    for symbol in SYMBOLS:
        market[symbol] = shock(market[symbol], close=0.95)
    signals = SignalDetector('stocks').scan(market)
    assert [s.type for s in signals] == ['market_move']
    assert signals[0].symbol is None and 'selloff' in signals[0].title


def test_crypto_needs_a_bigger_gap(market):
    market['SGE'] = shock(market['SGE'], open_=1.03)
    detector_stocks = SignalDetector('stocks', {'thresholds': {'gap_z': 1.0}})
    detector_crypto = SignalDetector('crypto', {'thresholds': {'gap_z': 1.0}})
    assert any(s.type == 'gap' and s.symbol == 'SGE' for s in detector_stocks.scan(market, session='open'))
    assert not any(s.type == 'gap' and s.symbol == 'SGE' for s in detector_crypto.scan(market, session='open'))


def test_lookback_scans_several_days(market):
    market['SGF'] = shock(market['SGF'], close=0.8)
    one = SignalDetector('stocks').scan(market, lookback=1)
    many = SignalDetector('stocks').scan(market, lookback=20)
    assert len(many) >= len(one) >= 1


def test_analysis_signals():
    current = [
        {'symbol': 'AAA', 'picked': True, 'company_name': 'A', 'vol_up_probability': 0.8, 'volatility': 0.2, 'vol_forecast': 0.3},
        {'symbol': 'BBB', 'picked': True, 'vol_up_probability': 0.9, 'volatility': 0.2, 'vol_forecast': 0.21},
        {'symbol': 'CCC', 'picked': False, 'vol_up_probability': 0.95, 'volatility': 0.2, 'vol_forecast': 0.5},
    ]
    signals = detect_from_analysis('stocks', current, ['AAA', 'DDD'], '2026-10-27')
    change = next(s for s in signals if s.type == 'portfolio_change')
    assert change.data == {'added': ['BBB'], 'removed': ['DDD']}
    assert [s.symbol for s in signals if s.type == 'volatility_rising'] == ['AAA']
    assert not [s for s in detect_from_analysis('stocks', current, None, '2026-10-27') if s.type == 'portfolio_change']


@pytest.fixture
def notifications(tmp_path):
    return NotificationStore(Store(str(tmp_path / 'n.db')))


def signal(type_='unusual_move', severity='warning', symbol='AAA', day='2026-10-27'):
    from src.signals import Signal
    return Signal(type=type_, severity=severity, symbol=symbol, title='t', body='b', event_date=day)


def test_dedupe_and_cooldown(notifications):
    notifier = Notifier(notifications, cooldown_hours=12)
    assert len(notifier.publish('stocks', [signal()])) == 1
    assert notifier.publish('stocks', [signal()]) == []                        # same event again
    assert notifier.publish('stocks', [signal(day='2026-10-28')]) == []        # within cooldown
    assert len(notifier.publish('stocks', [signal(severity='critical', day='2026-10-28')])) == 1  # escalation
    assert len(notifier.publish('crypto', [signal()])) == 1                    # other universe is separate
    assert len(notifier.publish('stocks', [signal(symbol=None, type_='market_move')])) == 1


def test_read_state_and_counts(notifications):
    notifier = Notifier(notifications)
    created = notifier.publish('stocks', [signal(symbol='A'), signal(symbol='B', severity='critical')])
    assert notifications.unread_counts()['stocks'] == {'total': 2, 'critical': 1, 'warning': 1, 'info': 0}
    notifications.mark_read(created[0]['id'])
    assert notifications.unread_counts()['stocks']['total'] == 1
    assert notifications.mark_all_read('stocks') == 1
    assert notifications.unread_counts() == {}
    assert all(n['read'] for n in notifications.list('stocks'))


def test_channels_receive_new_notifications_only(notifications):
    class Recorder:
        name = 'recorder'
        def __init__(self):
            self.sent = []
        def deliver(self, n):
            self.sent.append(n['title'])

    class Broken:
        name = 'broken'
        def deliver(self, n):
            raise RuntimeError('down')

    recorder = Recorder()
    notifier = Notifier(notifications, channels=[Broken(), recorder])
    notifier.publish('stocks', [signal(), signal()])
    assert recorder.sent == ['t']  # duplicate not re-sent; a failing channel does not block others


def test_scan_schedule_twice_a_day_and_weekends():
    schedule = {'timezone': 'America/New_York', 'open': '09:45', 'close': '16:15', 'stocks_weekdays_only': True}
    friday_after_close = datetime(2026, 10, 30, 21, 0, tzinfo=timezone.utc)  # 17:00 New York
    stocks = scan_times(schedule, 'stocks', friday_after_close)
    crypto = scan_times(schedule, 'crypto', friday_after_close)
    assert [(t.strftime('%a %H:%M'), s) for t, s in stocks[:2]] == [('Mon 09:45', 'open'), ('Mon 16:15', 'close')]
    assert [(t.strftime('%a %H:%M'), s) for t, s in crypto[:2]] == [('Sat 09:45', 'open'), ('Sat 16:15', 'close')]
    assert stocks[0][0].utcoffset().total_seconds() == -5 * 3600  # clocks changed on 1 November


def test_alert_rate_on_ordinary_data_is_low():
    """Over many ordinary days, alerts should be rare (about 1% of asset-days)."""
    data = generate_market(SYMBOLS, days=200, seed=4)
    alerts = SignalDetector('stocks').scan(data, lookback=120)
    assert len(alerts) / (120 * len(SYMBOLS)) < 0.03
