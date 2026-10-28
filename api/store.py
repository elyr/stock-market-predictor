"""
SQLite persistence for analysis runs, predictions, outcomes and backtests.

Every analysis run stores the full ranking (not only the picks), with the entry
price and date of each asset. Once the run's horizon has passed, the outcome is
filled in from later prices: each asset's realised return, the universe average,
the portfolio's return and excess, and the rank IC. Because predictions are
written before their outcomes exist, the track record cannot be curve-fitted
after the fact.

Runs seeded from a walk-forward backtest (demo mode) are flagged ``simulated``.
"""

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    universe TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data_date TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    top_n INTEGER NOT NULL,
    demo INTEGER NOT NULL DEFAULT 0,
    simulated INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT NOT NULL,
    evaluated_at TEXT,
    exit_date TEXT,
    portfolio_return REAL,
    universe_return REAL,
    excess_return REAL,
    rank_ic REAL
);
CREATE INDEX IF NOT EXISTS idx_runs_universe ON runs (universe, data_date);

CREATE TABLE IF NOT EXISTS predictions (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    rank INTEGER NOT NULL,
    picked INTEGER NOT NULL,
    weight REAL,
    composite_score REAL,
    ml_probability REAL,
    entry_price REAL,
    realized_return REAL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (run_id, symbol)
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    universe TEXT NOT NULL,
    type TEXT NOT NULL,
    severity TEXT NOT NULL,
    symbol TEXT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    data_json TEXT NOT NULL,
    event_date TEXT NOT NULL,
    session TEXT,
    created_at TEXT NOT NULL,
    read_at TEXT,
    dedupe_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_notifications_universe ON notifications (universe, created_at);

CREATE TABLE IF NOT EXISTS backtests (
    id TEXT PRIMARY KEY,
    universe TEXT NOT NULL,
    created_at TEXT NOT NULL,
    demo INTEGER NOT NULL DEFAULT 0,
    params_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Store:
    """Thread-safe access to the SQLite database."""

    def __init__(self, path: str):
        import os
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys = ON')
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------ runs

    def save_run(self, universe: str, data_date: str, horizon: int, top_n: int, summary: Dict[str, Any],
                 predictions: List[Dict[str, Any]], demo: bool = False, simulated: bool = False,
                 created_at: Optional[str] = None) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, universe, created_at, data_date, horizon, top_n, demo, simulated, summary_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, universe, created_at or now_iso(), data_date, horizon, top_n, int(demo), int(simulated),
                 json.dumps(summary)))
            conn.executemany(
                "INSERT INTO predictions (run_id, symbol, rank, picked, weight, composite_score, ml_probability, "
                "entry_price, realized_return, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(run_id, p['symbol'], p['rank'], int(p.get('picked', False)), p.get('weight'),
                  p.get('composite_score'), p.get('ml_probability'), p.get('entry_price'),
                  p.get('realized_return'), json.dumps(p.get('payload', {}))) for p in predictions])
        return run_id

    def record_outcome(self, run_id: str, exit_date: str, returns: Dict[str, float],
                       portfolio_return: float, universe_return: float, rank_ic: Optional[float]) -> None:
        with self._connect() as conn:
            conn.executemany("UPDATE predictions SET realized_return = ? WHERE run_id = ? AND symbol = ?",
                             [(r, run_id, s) for s, r in returns.items()])
            conn.execute(
                "UPDATE runs SET evaluated_at = ?, exit_date = ?, portfolio_return = ?, universe_return = ?, "
                "excess_return = ?, rank_ic = ? WHERE id = ?",
                (now_iso(), exit_date, portfolio_return, universe_return, portfolio_return - universe_return,
                 rank_ic, run_id))

    @staticmethod
    def _run_dict(row: sqlite3.Row, with_summary: bool = True) -> Dict[str, Any]:
        run = {k: row[k] for k in row.keys() if k != 'summary_json'}
        run['demo'] = bool(run['demo'])
        run['simulated'] = bool(run['simulated'])
        if with_summary:
            run['summary'] = json.loads(row['summary_json'])
        return run

    def latest_run(self, universe: str, include_simulated: bool = False) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM runs WHERE universe = ?" + ("" if include_simulated else " AND simulated = 0") + \
                " ORDER BY created_at DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(query, (universe,)).fetchone()
        return self._run_dict(row) if row else None

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._run_dict(row) if row else None

    def list_runs(self, universe: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM runs WHERE universe = ? ORDER BY data_date DESC, created_at DESC "
                                "LIMIT ?", (universe, limit)).fetchall()
        return [self._run_dict(r, with_summary=False) for r in rows]

    def pending_runs(self, universe: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM runs WHERE universe = ? AND evaluated_at IS NULL "
                                "ORDER BY data_date", (universe,)).fetchall()
        return [self._run_dict(r, with_summary=False) for r in rows]

    def predictions(self, run_id: str, picked_only: bool = False) -> List[Dict[str, Any]]:
        query = "SELECT * FROM predictions WHERE run_id = ?" + (" AND picked = 1" if picked_only else "") + \
                " ORDER BY rank"
        with self._connect() as conn:
            rows = conn.execute(query, (run_id,)).fetchall()
        result = []
        for r in rows:
            item = {k: r[k] for k in r.keys() if k != 'payload_json'}
            item['picked'] = bool(item['picked'])
            item['payload'] = json.loads(r['payload_json'])
            result.append(item)
        return result

    def has_runs(self, universe: str) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM runs WHERE universe = ? LIMIT 1", (universe,)).fetchone() is not None

    # ------------------------------------------------------------- backtests

    def save_backtest(self, universe: str, params: Dict[str, Any], result: Dict[str, Any], demo: bool = False) -> str:
        backtest_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute("INSERT INTO backtests (id, universe, created_at, demo, params_json, result_json) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (backtest_id, universe, now_iso(), int(demo), json.dumps(params), json.dumps(result)))
        return backtest_id

    def get_backtest(self, backtest_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM backtests WHERE id = ?", (backtest_id,)).fetchone()
        if not row:
            return None
        return {'id': row['id'], 'universe': row['universe'], 'created_at': row['created_at'],
                'demo': bool(row['demo']), 'params': json.loads(row['params_json']),
                'result': json.loads(row['result_json'])}

    def list_backtests(self, universe: str, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, universe, created_at, demo, params_json, result_json FROM backtests "
                                "WHERE universe = ? ORDER BY created_at DESC LIMIT ?", (universe, limit)).fetchall()
        result = []
        for row in rows:
            data = json.loads(row['result_json'])
            result.append({'id': row['id'], 'universe': row['universe'], 'created_at': row['created_at'],
                           'demo': bool(row['demo']), 'params': json.loads(row['params_json']),
                           'settings': data.get('settings'), 'headline': data.get('headline')})
        return result


SEVERITY_RANK = {'info': 0, 'warning': 1, 'critical': 2}


def _notification_dict(row: sqlite3.Row) -> Dict[str, Any]:
    item = {k: row[k] for k in row.keys() if k not in ('data_json', 'dedupe_key')}
    item['data'] = json.loads(row['data_json'])
    item['read'] = row['read_at'] is not None
    return item


class NotificationStore:
    """
    Notifications live in the same database. Two rules keep them quiet:

    * the same event on the same day (same dedupe key) is stored once, and
    * an alert of the same type for the same asset is suppressed for
      ``cooldown_hours`` unless the new one is more severe.
    """

    def __init__(self, store: Store):
        self.store = store

    def add(self, universe: str, signal: Dict[str, Any], dedupe_key: str, session: Optional[str] = None,
            cooldown_hours: float = 12, created_at: Optional[str] = None) -> Optional[int]:
        created = created_at or now_iso()
        with self.store._connect() as conn:
            if conn.execute("SELECT 1 FROM notifications WHERE dedupe_key = ?", (dedupe_key,)).fetchone():
                return None
            since = (datetime.fromisoformat(created) - timedelta(hours=cooldown_hours)).isoformat(timespec='seconds')
            recent = conn.execute(
                "SELECT severity FROM notifications WHERE universe = ? AND type = ? AND symbol IS ? AND created_at >= ?",
                (universe, signal['type'], signal.get('symbol'), since)).fetchall()
            if recent and max(SEVERITY_RANK[r['severity']] for r in recent) >= SEVERITY_RANK[signal['severity']]:
                return None
            cursor = conn.execute(
                "INSERT INTO notifications (universe, type, severity, symbol, title, body, data_json, event_date, "
                "session, created_at, dedupe_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (universe, signal['type'], signal['severity'], signal.get('symbol'), signal['title'], signal['body'],
                 json.dumps(signal.get('data', {})), signal['event_date'], session, created, dedupe_key))
            return int(cursor.lastrowid)

    def get(self, notification_id: int) -> Optional[Dict[str, Any]]:
        with self.store._connect() as conn:
            row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,)).fetchone()
        return _notification_dict(row) if row else None

    def list(self, universe: Optional[str] = None, unread_only: bool = False, limit: int = 100) -> List[Dict[str, Any]]:
        query, params = "SELECT * FROM notifications WHERE 1 = 1", []
        if universe:
            query += " AND universe = ?"
            params.append(universe)
        if unread_only:
            query += " AND read_at IS NULL"
        query += " ORDER BY event_date DESC, created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self.store._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_notification_dict(r) for r in rows]

    def unread_counts(self) -> Dict[str, Dict[str, int]]:
        with self.store._connect() as conn:
            rows = conn.execute("SELECT universe, severity, COUNT(*) AS n FROM notifications WHERE read_at IS NULL "
                                "GROUP BY universe, severity").fetchall()
        counts: Dict[str, Dict[str, int]] = {}
        for r in rows:
            entry = counts.setdefault(r['universe'], {'total': 0, 'critical': 0, 'warning': 0, 'info': 0})
            entry[r['severity']] = r['n']
            entry['total'] += r['n']
        return counts

    def mark_read(self, notification_id: int) -> bool:
        with self.store._connect() as conn:
            cursor = conn.execute("UPDATE notifications SET read_at = ? WHERE id = ? AND read_at IS NULL",
                                  (now_iso(), notification_id))
            exists = conn.execute("SELECT 1 FROM notifications WHERE id = ?", (notification_id,)).fetchone()
        return bool(exists) or cursor.rowcount > 0

    def mark_all_read(self, universe: Optional[str] = None) -> int:
        query, params = "UPDATE notifications SET read_at = ? WHERE read_at IS NULL", [now_iso()]
        if universe:
            query += " AND universe = ?"
            params.append(universe)
        with self.store._connect() as conn:
            return conn.execute(query, params).rowcount
