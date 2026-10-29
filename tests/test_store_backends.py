"""
The store on SQLite and PostgreSQL: the same operations, the same results.
PostgreSQL runs when TEST_DATABASE_URL is set (see conftest.py).
"""

import sqlite3

import pytest

from api.store import NotificationStore, Store
from api.jobs import JobManager


def signal(severity='warning', symbol='BTC-USD', day='2026-01-05'):
    return {'type': 'unusual_move', 'severity': severity, 'symbol': symbol, 'title': 't', 'body': 'b',
            'event_date': day, 'data': {'move': 0.1}}


def test_runs_predictions_and_outcomes(database):
    store = Store(database)
    run_id = store.save_run('crypto', '2026-01-05', 5, 2, {'model': {'version': '3'}}, [
        {'symbol': 'BTC-USD', 'rank': 1, 'picked': True, 'weight': 0.6, 'composite_score': 71.2,
         'ml_probability': 0.58, 'entry_price': 100.0, 'payload': {'symbol': 'BTC-USD', 'x': [1, 2]}},
        {'symbol': 'ETH-USD', 'rank': 2, 'picked': False, 'composite_score': 60.0, 'entry_price': 10.0,
         'payload': {'symbol': 'ETH-USD'}},
    ], demo=True)
    assert store.has_runs('crypto') and not store.has_runs('stocks')
    latest = store.latest_run('crypto')
    assert latest['id'] == run_id and latest['summary'] == {'model': {'version': '3'}} and latest['demo'] is True
    assert [p['symbol'] for p in store.predictions(run_id, picked_only=True)] == ['BTC-USD']
    assert store.predictions(run_id)[0]['payload'] == {'symbol': 'BTC-USD', 'x': [1, 2]}
    assert [r['id'] for r in store.pending_runs('crypto')] == [run_id]

    store.record_outcome(run_id, '2026-01-12', {'BTC-USD': 0.05, 'ETH-USD': -0.02}, 0.05, 0.015, 0.4)
    run = store.get_run(run_id)
    assert run['excess_return'] == pytest.approx(0.035) and run['rank_ic'] == pytest.approx(0.4)
    assert store.pending_runs('crypto') == []
    assert store.predictions(run_id)[1]['realized_return'] == pytest.approx(-0.02)
    assert store.list_runs('crypto')[0]['id'] == run_id


def test_backtests_and_experiments(database):
    store = Store(database)
    backtest_id = store.save_backtest('stocks', {'test_days': 60}, {'headline': {'ic_mean': 0.02}})
    store.save_backtest_predictions(backtest_id, [{'date': '2026-01-05', 'symbol': 'A'}])
    store.save_backtest_predictions(backtest_id, [{'date': '2026-01-06', 'symbol': 'B'}])  # replaces
    assert store.backtest_predictions(backtest_id) == [{'date': '2026-01-06', 'symbol': 'B'}]
    assert store.backtests_with_predictions('stocks')[0]['id'] == backtest_id
    assert store.list_backtests('stocks')[0]['headline'] == {'ic_mean': 0.02}

    experiment_id = store.create_experiment('stocks', 'Less momentum', {'weights.momentum_score': 0.1}, 5)
    store.update_experiment(experiment_id, status='done', dev_json={'headline': 'ok'})
    experiment = store.get_experiment(experiment_id)
    assert experiment['status'] == 'done' and experiment['development'] == {'headline': 'ok'}
    with pytest.raises(ValueError):
        store.update_experiment(experiment_id, not_a_column=1)


def test_notifications_dedupe_and_cooldown(database):
    notes = NotificationStore(Store(database))
    first = notes.add('crypto', signal(), 'key-1')
    assert isinstance(first, int)
    assert notes.add('crypto', signal(), 'key-1') is None                      # same event
    assert notes.add('crypto', signal(), 'key-2') is None                      # cooldown, same severity
    assert notes.add('crypto', signal(severity='critical'), 'key-3') is not None  # more severe
    assert notes.add('crypto', signal(symbol=None), 'key-4') is not None       # market-wide (no symbol)
    assert notes.add('crypto', signal(symbol=None), 'key-5') is None           # ... and its cooldown
    assert notes.unread_counts()['crypto']['total'] == 3
    assert notes.mark_read(first) and notes.get(first)['read']
    assert not notes.mark_read(99999)
    assert notes.mark_all_read('crypto') == 2
    assert notes.list('crypto', unread_only=True) == []


def test_only_one_active_job_per_kind_and_universe(database):
    store = Store(database)
    base = {'kind': 'analysis', 'universe': 'stocks', 'status': 'queued', 'message': '', 'params_json': '{}',
            'dedupe': 1, 'created_at': '2026-01-01T00:00:00+00:00'}
    assert store.insert_job({**base, 'id': 'a'})
    assert not store.insert_job({**base, 'id': 'b'})                      # refused by the unique index
    assert store.insert_job({**base, 'id': 'c', 'dedupe': 0})             # jobs that allow copies
    assert store.insert_job({**base, 'id': 'd', 'universe': 'crypto'})    # another universe
    store.update_job('a', status='succeeded')
    assert store.insert_job({**base, 'id': 'e'})                          # the first one finished
    assert {(r['kind'], r['universe'], r['status'], r['n']) for r in store.job_counts()} == {
        ('analysis', 'stocks', 'succeeded', 1), ('analysis', 'stocks', 'queued', 2),
        ('analysis', 'crypto', 'queued', 1)}


def test_inline_jobs_run_and_survive_a_restart(database):
    store = Store(database)
    manager = JobManager(store)
    job = manager.submit('analysis', 'stocks', func=lambda job: {'ok': True})
    manager.shutdown()
    import time
    for _ in range(50):
        if manager.get(job.id).status == 'succeeded':
            break
        time.sleep(0.1)
    assert manager.get(job.id).result == {'ok': True}
    # A job left running when the server stopped is marked failed at the next start
    store.insert_job({'id': 'stuck', 'kind': 'scan', 'universe': 'crypto', 'status': 'running', 'message': 'x',
                      'params_json': '{}', 'dedupe': 1, 'created_at': '2026-01-01T00:00:00+00:00'})
    JobManager(store).shutdown()
    stuck = store.get_job('stuck')
    assert stuck['status'] == 'failed' and 'restarted' in stuck['error']


def test_existing_sqlite_database_is_adopted(tmp_path):
    """A database made before migrations existed keeps its data and gains the new tables."""
    path = tmp_path / 'old.db'
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE runs (id TEXT PRIMARY KEY, universe TEXT NOT NULL, created_at TEXT NOT NULL,
            data_date TEXT NOT NULL, horizon INTEGER NOT NULL, top_n INTEGER NOT NULL,
            demo INTEGER NOT NULL DEFAULT 0, simulated INTEGER NOT NULL DEFAULT 0, summary_json TEXT NOT NULL,
            evaluated_at TEXT, exit_date TEXT, portfolio_return REAL, universe_return REAL, excess_return REAL,
            rank_ic REAL);
        INSERT INTO runs (id, universe, created_at, data_date, horizon, top_n, summary_json)
            VALUES ('old1', 'stocks', '2025-12-01T00:00:00+00:00', '2025-12-01', 5, 10, '{}');
    """)
    conn.commit()
    conn.close()
    store = Store(str(path))
    assert store.latest_run('stocks')['id'] == 'old1'
    assert store.list_jobs() == [] and NotificationStore(store).list() == []
