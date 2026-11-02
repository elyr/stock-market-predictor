"""My portfolio: holdings from transactions, history against a benchmark, risk warnings and the API."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.settings import Settings
from src.personal.portfolio import (DEFAULT_RULES, TransactionError, apply_transactions, portfolio_volatility,
                                    risk_label, risk_warnings, value_history, weekly_range)


def tx(symbol, side, day, quantity, price, fees=0.0):
    return {'symbol': symbol, 'side': side, 'trade_date': day, 'quantity': quantity, 'price': price, 'fees': fees}


# ------------------------------------------------------------------ holdings

def test_average_cost_and_realised_gain():
    holdings = apply_transactions([
        tx('AAA', 'buy', '2026-01-02', 10, 100, fees=10),   # cost 1010
        tx('AAA', 'buy', '2026-02-02', 10, 120),            # cost 2210, average 110.5
        tx('AAA', 'sell', '2026-03-02', 5, 130, fees=5),    # gain 5 * (130 - 110.5) - 5 = 92.5
    ])
    h = holdings['AAA']
    assert h.quantity == 15
    assert h.average_cost == pytest.approx(110.5)
    assert h.cost_basis == pytest.approx(15 * 110.5)
    assert h.realized == pytest.approx(92.5)
    assert h.fees == 15 and h.trades == 3 and h.first_date == '2026-01-02'


def test_selling_everything_resets_the_position():
    h = apply_transactions([tx('AAA', 'buy', '2026-01-02', 3, 50), tx('AAA', 'sell', '2026-01-09', 3, 40)])['AAA']
    assert h.quantity == 0 and h.cost_basis == 0 and h.average_cost is None
    assert h.realized == pytest.approx(-30)


def test_cannot_sell_more_than_held_on_that_date():
    with pytest.raises(TransactionError):
        apply_transactions([tx('AAA', 'sell', '2026-01-01', 1, 10), tx('AAA', 'buy', '2026-01-05', 5, 10)])


# ------------------------------------------------------------------ history

def test_benchmark_gets_the_same_cash_flows():
    days = pd.bdate_range('2026-01-01', periods=6)
    closes = {'AAA': pd.Series([10, 11, 12, 12, 13, 14], index=days, dtype=float)}
    benchmark = pd.Series([1.0, 1.0, 1.1, 1.1, 1.1, 1.21], index=days)
    history = value_history([tx('AAA', 'buy', str(days[0].date()), 10, 10),
                             tx('AAA', 'sell', str(days[3].date()), 5, 12)], closes, benchmark)
    assert history['value'].iloc[0] == 100 and history['value'].iloc[-1] == 5 * 14
    assert history['invested'].iloc[-1] == pytest.approx(100 - 60)
    # 100 in at level 1.0 = 100 units; 60 out at 1.1 = 54.5 units; 45.45 units at 1.21
    assert history['benchmark_value'].iloc[-1] == pytest.approx((100 - 60 / 1.1) * 1.21)


def test_history_uses_no_future_prices():
    days = pd.bdate_range('2026-01-01', periods=10)
    closes = {'AAA': pd.Series(np.arange(10, 20, dtype=float), index=days)}
    full = value_history([tx('AAA', 'buy', '2026-01-01', 1, 10)], closes)
    cut = value_history([tx('AAA', 'buy', '2026-01-01', 1, 10)], {'AAA': closes['AAA'][:5]})
    pd.testing.assert_series_equal(full['value'][:5], cut['value'], check_freq=False)


# ------------------------------------------------------------------ risk

def test_portfolio_volatility_falls_with_diversification():
    rng = np.random.default_rng(0)
    days = pd.bdate_range('2025-01-01', periods=200)
    closes = {s: pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 200))), index=days) for s in 'ABCD'}
    one = portfolio_volatility({'A': 1.0}, closes)
    four = portfolio_volatility({s: 0.25 for s in 'ABCD'}, closes)
    assert one == pytest.approx(0.02 * np.sqrt(252), rel=0.2)
    assert four < 0.7 * one  # independent assets: about half


def test_warnings_explain_broken_rules_in_plain_language():
    positions = [{'symbol': 'AAA', 'weight': 0.6, 'sector': 'Technology', 'rank': 95, 'universe_size': 100,
                  'vol_up_probability': 0.8},
                 {'symbol': 'BBB', 'weight': 0.4, 'sector': 'Technology'}]
    found = risk_warnings(positions, volatility=0.45, rules=DEFAULT_RULES)
    kinds = [w['kind'] for w in found]
    assert kinds[0] == 'position' and found[0]['level'] == 'high'
    assert {'position', 'sector', 'volatility', 'concentration', 'volatility_rising', 'model_low'} <= set(kinds)
    assert '60%' in found[0]['message'] and 'AAA' in found[0]['message']
    assert risk_warnings(positions, 0.45, DEFAULT_RULES, sectors=False) and \
        'sector' not in [w['kind'] for w in risk_warnings(positions, 0.45, DEFAULT_RULES, sectors=False)]
    calm = [{'symbol': s, 'weight': 0.1, 'sector': f'S{i}'} for i, s in enumerate('ABCDEFGHIJ')]
    assert risk_warnings(calm, 0.15, DEFAULT_RULES) == []


def test_labels_and_ranges():
    assert risk_label(0.1) == 'Calm' and risk_label(0.5) == 'Very high' and risk_label(None) is None
    r = weekly_range(1000, 0.2, 5, 252)
    assert r['low'] < 1000 < r['high'] and r['high'] / 1000 - 1 == pytest.approx(1 - r['low'] / 1000, rel=0.1)


# ------------------------------------------------------------------ API

@pytest.fixture
def client(fast_config_path, tmp_path):
    settings = Settings(config_path=fast_config_path, demo_mode=True, seed_demo=False,
                        database_path=str(tmp_path / 'db.sqlite'), model_registry='off')
    with TestClient(create_app(settings)) as c:
        yield c


def test_portfolio_api_round_trip(client):
    assert client.get('/api/stocks/portfolio').json()['empty'] is True
    day = (date.today() - timedelta(days=60)).isoformat()
    later = (date.today() - timedelta(days=20)).isoformat()
    for symbol, qty in (('AAPL', 10), ('MSFT', 5)):
        r = client.post('/api/stocks/portfolio/transactions',
                        json={'symbol': symbol.lower(), 'side': 'buy', 'trade_date': day, 'quantity': qty, 'price': 100})
        assert r.status_code == 201 and r.json()['symbol'] == symbol
    sale = client.post('/api/stocks/portfolio/transactions',
                       json={'symbol': 'AAPL', 'side': 'sell', 'trade_date': later, 'quantity': 4, 'price': 110})
    assert sale.status_code == 201

    view = client.get('/api/stocks/portfolio').json()
    assert view['empty'] is False and view['summary']['positions'] == 2
    by_symbol = {p['symbol']: p for p in view['positions']}
    assert by_symbol['AAPL']['quantity'] == 6
    assert by_symbol['AAPL']['realized'] == pytest.approx(40)
    assert sum(p['weight'] for p in view['positions']) == pytest.approx(1)
    assert view['history'] and view['history'][-1]['benchmark'] is not None
    assert any(w['kind'] == 'concentration' for w in view['warnings'])
    assert view['summary']['risk_label'] in ('Calm', 'Moderate', 'High', 'Very high')

    csv = client.get('/api/stocks/portfolio/transactions.csv')
    assert csv.status_code == 200 and csv.text.count('\n') == 4

    # The buy cannot be removed while the later sale depends on it
    buy_id = next(t['id'] for t in view['transactions'] if t['symbol'] == 'AAPL' and t['side'] == 'buy')
    assert client.delete(f'/api/stocks/portfolio/transactions/{buy_id}').status_code == 422
    sale_id = sale.json()['id']
    assert client.delete(f'/api/stocks/portfolio/transactions/{sale_id}').status_code == 204
    assert client.delete(f'/api/stocks/portfolio/transactions/{sale_id}').status_code == 404


def test_portfolio_api_rejects_impossible_trades(client):
    today = date.today()
    post = lambda body: client.post('/api/stocks/portfolio/transactions', json=body)  # noqa: E731
    base = {'symbol': 'AAPL', 'side': 'buy', 'trade_date': today.isoformat(), 'quantity': 1, 'price': 10}
    assert post({**base, 'side': 'sell'}).status_code == 422                       # nothing to sell
    assert post({**base, 'trade_date': (today + timedelta(days=3)).isoformat()}).status_code == 422
    assert post({**base, 'quantity': 0}).status_code == 422
    assert post({**base, 'symbol': 'BTC-USD'}).status_code == 422                  # crypto on the stocks dashboard
    assert client.post('/api/crypto/portfolio/transactions', json={**base, 'symbol': 'AAPL'}).status_code == 422
    # Each dashboard keeps its own portfolio
    assert post(base).status_code == 201
    assert client.get('/api/crypto/portfolio').json()['empty'] is True
