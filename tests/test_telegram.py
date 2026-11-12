"""
Tests for Telegram delivery. The HTTP call is always mocked: nothing here reaches the network.
"""

import logging

import pytest
import requests

from api.main import create_app
from api.notifications import Notifier
from api.settings import Settings
from api.store import NotificationStore, Store
from api.telegram import API_URL, TelegramChannel, notification_channels
from src.signals import Signal

TOKEN = '123456:SECRET-token-value'


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code, self._body, self.ok = status, body or {'ok': True}, status < 400

    def json(self):
        return self._body


@pytest.fixture
def sent(monkeypatch):
    """Record every call to requests.post and answer 200."""
    calls = []

    def post(url, **kwargs):
        calls.append({'url': url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr('api.telegram.requests.post', post)
    return calls


def note(type_='unusual_move', severity='warning', title='AAA up 9% today', body='AAA moved +9%.'):
    return {'id': 1, 'type': type_, 'severity': severity, 'title': title, 'body': body}


def test_sends_a_warning_to_the_chat_with_timeouts(sent):
    TelegramChannel(TOKEN, '42').deliver(note())
    assert len(sent) == 1
    call = sent[0]
    assert call['url'] == API_URL.format(token=TOKEN)
    assert call['json']['chat_id'] == '42'
    assert call['json']['text'] == 'AAA up 9% today\n\nAAA moved +9%.'
    connect, read = call['timeout']
    assert 0 < connect <= 10 and 0 < read <= 30


def test_minimum_severity_defaults_to_warning_and_trend_enter_is_always_sent(sent):
    channel = TelegramChannel(TOKEN, '42')
    for item in (note(severity='info'), note(type_='portfolio_change', severity='info')):
        channel.deliver(item)
    assert sent == []                                                  # info is below the default
    channel.deliver(note(severity='critical'))
    channel.deliver(note(type_='trend_exit', severity='warning'))
    channel.deliver(note(type_='trend_enter', severity='info'))        # always sent
    assert len(sent) == 3


@pytest.mark.parametrize('minimum, expected', [('info', 3), ('warning', 2), ('critical', 1)])
def test_minimum_severity_is_configurable(sent, minimum, expected):
    channel = TelegramChannel(TOKEN, '42', min_severity=minimum)
    for severity in ('info', 'warning', 'critical'):
        channel.deliver(note(severity=severity))
    assert len(sent) == expected


def test_unknown_minimum_severity_falls_back_to_warning(sent, caplog):
    with caplog.at_level(logging.WARNING):
        channel = TelegramChannel(TOKEN, '42', min_severity='loud')
    assert channel.min_severity == 'warning' and 'loud' in caplog.text


def test_long_messages_are_cut_to_telegrams_limit(sent):
    TelegramChannel(TOKEN, '42').deliver(note(body='x' * 10_000))
    assert len(sent[0]['json']['text']) == 4096


def test_a_network_error_is_logged_without_the_token_and_does_not_raise(monkeypatch, caplog):
    def post(url, **kwargs):  # the real exception text quotes the address, which holds the token
        raise requests.ConnectionError(f"HTTPSConnectionPool: Max retries exceeded with url: {url}")

    monkeypatch.setattr('api.telegram.requests.post', post)
    with caplog.at_level(logging.DEBUG):
        TelegramChannel(TOKEN, '42').deliver(note())
    assert 'ConnectionError' in caplog.text
    assert TOKEN not in caplog.text and 'SECRET' not in caplog.text


def test_a_timeout_and_a_refusal_are_logged_and_do_not_raise(monkeypatch, caplog):
    channel = TelegramChannel(TOKEN, '42')
    monkeypatch.setattr('api.telegram.requests.post', lambda *a, **k: (_ for _ in ()).throw(requests.Timeout()))
    channel.deliver(note())
    monkeypatch.setattr('api.telegram.requests.post',
                        lambda *a, **k: FakeResponse(401, {'ok': False, 'description': 'Unauthorized'}))
    with caplog.at_level(logging.WARNING):
        channel.deliver(note())
    assert 'Timeout' in caplog.text and 'HTTP 401' in caplog.text and 'Unauthorized' in caplog.text
    assert TOKEN not in caplog.text


def test_a_failing_telegram_does_not_break_the_notifier(monkeypatch, tmp_path):
    def post(url, **kwargs):
        raise requests.ConnectionError(url)

    monkeypatch.setattr('api.telegram.requests.post', post)
    store = NotificationStore(Store(str(tmp_path / 'n.db')))
    notifier = Notifier(store, channels=[TelegramChannel(TOKEN, '42')])
    signal = Signal(type='unusual_move', severity='critical', symbol='AAA', title='t', body='b',
                    event_date='2026-10-27')
    assert len(notifier.publish('stocks', [signal])) == 1          # still stored for the app
    assert len(store.list('stocks')) == 1


def test_the_channel_exists_only_when_both_variables_are_set():
    both = Settings(telegram_bot_token=TOKEN, telegram_chat_id='42', telegram_min_severity='info')
    channels = notification_channels(both)
    assert [type(c) for c in channels] == [TelegramChannel] and channels[0].min_severity == 'info'
    assert notification_channels(Settings(telegram_bot_token=TOKEN)) == []
    assert notification_channels(Settings(telegram_chat_id='42')) == []
    assert notification_channels(Settings()) == []


def test_settings_read_the_environment_and_keep_the_token_out_of_the_repr(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', f' {TOKEN} ')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '-100123')
    monkeypatch.setenv('TELEGRAM_MIN_SEVERITY', 'Critical')
    settings = Settings.from_env()
    assert (settings.telegram_bot_token, settings.telegram_chat_id, settings.telegram_min_severity) == \
           (TOKEN, '-100123', 'critical')
    assert TOKEN not in repr(settings) and '-100123' not in repr(settings)


def test_the_app_adds_the_channel_only_when_configured(fast_config_path, tmp_path):
    def channels(**telegram):
        settings = Settings(config_path=fast_config_path, demo_mode=True, seed_demo=False,
                            database_path=str(tmp_path / 'app.db'), frontend_dist=str(tmp_path), **telegram)
        return create_app(settings).state.app_state.notifier.channels

    assert channels() == []
    assert [c.name for c in channels(telegram_bot_token=TOKEN, telegram_chat_id='42')] == ['telegram']
