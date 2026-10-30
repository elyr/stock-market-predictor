"""
Persistence for analysis runs, predictions, outcomes, backtests, experiments,
notifications and jobs, on SQLite (default) or PostgreSQL (see api/db.py).

Every analysis run stores the full ranking (not only the picks), with the entry
price and date of each asset. Once the run's horizon has passed, the outcome is
filled in from later prices: each asset's realised return, the universe average,
the portfolio's return and excess, and the rank IC. Because predictions are
written before their outcomes exist, the track record cannot be curve-fitted
after the fact.

Runs seeded from a walk-forward backtest (demo mode) are flagged ``simulated``.
"""

import json
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import and_, delete, desc, func, insert, select, update
from sqlalchemy.engine import Connection, Engine, RowMapping

from api import db
from api.db import (backtest_predictions, backtests, experiments, forecast_batches, forecasts, jobs, notifications,
                    predictions, runs)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Store:
    """
    Database access for the app. ``target`` is a SQLite file path or a
    database URL; an existing engine can be passed instead.
    """

    def __init__(self, target: Optional[str] = None, engine: Optional[Engine] = None, migrate: bool = True):
        if engine is None:
            url = target if target and '://' in target else db.database_url(target or 'data/predictions.db')
            engine = db.make_engine(url)
        self.engine = engine
        self.url = db.safe_url(str(engine.url))
        self.backend = engine.dialect.name
        # SQLite allows one writer at a time; a process-wide lock avoids "database is locked" under load
        self._lock = threading.RLock() if db.is_sqlite(engine) else None
        if migrate:
            db.migrate(engine)

    @contextmanager
    def _connect(self) -> Iterator[Connection]:
        """A connection in a transaction, committed on success."""
        if self._lock is None:
            with self.engine.begin() as conn:
                yield conn
        else:
            with self._lock, self.engine.begin() as conn:
                yield conn

    def ping(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(select(1))

    # ------------------------------------------------------------------ runs

    def save_run(self, universe: str, data_date: str, horizon: int, top_n: int, summary: Dict[str, Any],
                 predictions_: List[Dict[str, Any]], demo: bool = False, simulated: bool = False,
                 created_at: Optional[str] = None) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(insert(runs).values(
                id=run_id, universe=universe, created_at=created_at or now_iso(), data_date=data_date,
                horizon=horizon, top_n=top_n, demo=int(demo), simulated=int(simulated),
                summary_json=json.dumps(summary)))
            if predictions_:
                conn.execute(insert(predictions), [{
                    'run_id': run_id, 'symbol': p['symbol'], 'rank': p['rank'], 'picked': int(p.get('picked', False)),
                    'weight': p.get('weight'), 'composite_score': p.get('composite_score'),
                    'ml_probability': p.get('ml_probability'), 'entry_price': p.get('entry_price'),
                    'realized_return': p.get('realized_return'), 'payload_json': json.dumps(p.get('payload', {})),
                } for p in predictions_])
        return run_id

    def record_outcome(self, run_id: str, exit_date: str, returns: Dict[str, float],
                       portfolio_return: float, universe_return: float, rank_ic: Optional[float]) -> None:
        with self._connect() as conn:
            for symbol, value in returns.items():
                conn.execute(update(predictions).where(and_(predictions.c.run_id == run_id,
                                                            predictions.c.symbol == symbol))
                             .values(realized_return=value))
            conn.execute(update(runs).where(runs.c.id == run_id).values(
                evaluated_at=now_iso(), exit_date=exit_date, portfolio_return=portfolio_return,
                universe_return=universe_return, excess_return=portfolio_return - universe_return, rank_ic=rank_ic))

    def set_run_fields(self, run_id: str, **fields: Any) -> None:
        """Change stored run fields directly (tests and maintenance)."""
        with self._connect() as conn:
            conn.execute(update(runs).where(runs.c.id == run_id).values(**fields))

    def set_prediction_fields(self, run_id: str, symbol: str, **fields: Any) -> None:
        with self._connect() as conn:
            conn.execute(update(predictions).where(and_(predictions.c.run_id == run_id,
                                                        predictions.c.symbol == symbol)).values(**fields))

    @staticmethod
    def _run_dict(row: RowMapping, with_summary: bool = True) -> Dict[str, Any]:
        run = {k: row[k] for k in row.keys() if k != 'summary_json'}
        run['demo'] = bool(run['demo'])
        run['simulated'] = bool(run['simulated'])
        if with_summary:
            run['summary'] = json.loads(row['summary_json'])
        return run

    def latest_run(self, universe: str, include_simulated: bool = False) -> Optional[Dict[str, Any]]:
        query = select(runs).where(runs.c.universe == universe)
        if not include_simulated:
            query = query.where(runs.c.simulated == 0)
        query = query.order_by(desc(runs.c.created_at)).limit(1)
        with self._connect() as conn:
            row = conn.execute(query).mappings().first()
        return self._run_dict(row) if row else None

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(select(runs).where(runs.c.id == run_id)).mappings().first()
        return self._run_dict(row) if row else None

    def list_runs(self, universe: str, limit: int = 200) -> List[Dict[str, Any]]:
        query = (select(*[c for c in runs.c if c.name != 'summary_json']).where(runs.c.universe == universe)
                 .order_by(desc(runs.c.data_date), desc(runs.c.created_at)).limit(limit))
        with self._connect() as conn:
            rows = conn.execute(query).mappings().all()
        return [self._run_dict(r, with_summary=False) for r in rows]

    def pending_runs(self, universe: str) -> List[Dict[str, Any]]:
        query = (select(*[c for c in runs.c if c.name != 'summary_json'])
                 .where(and_(runs.c.universe == universe, runs.c.evaluated_at.is_(None))).order_by(runs.c.data_date))
        with self._connect() as conn:
            rows = conn.execute(query).mappings().all()
        return [self._run_dict(r, with_summary=False) for r in rows]

    def predictions(self, run_id: str, picked_only: bool = False) -> List[Dict[str, Any]]:
        query = select(predictions).where(predictions.c.run_id == run_id)
        if picked_only:
            query = query.where(predictions.c.picked == 1)
        with self._connect() as conn:
            rows = conn.execute(query.order_by(predictions.c.rank)).mappings().all()
        result = []
        for r in rows:
            item = {k: r[k] for k in r.keys() if k != 'payload_json'}
            item['picked'] = bool(item['picked'])
            item['payload'] = json.loads(r['payload_json'])
            result.append(item)
        return result

    def has_runs(self, universe: str) -> bool:
        with self._connect() as conn:
            return conn.execute(select(runs.c.id).where(runs.c.universe == universe).limit(1)).first() is not None

    # ------------------------------------------------------------- backtests

    def save_backtest(self, universe: str, params: Dict[str, Any], result: Dict[str, Any], demo: bool = False) -> str:
        backtest_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(insert(backtests).values(id=backtest_id, universe=universe, created_at=now_iso(),
                                                  demo=int(demo), params_json=json.dumps(params),
                                                  result_json=json.dumps(result)))
        return backtest_id

    def save_backtest_predictions(self, backtest_id: str, rows: List[Dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.execute(delete(backtest_predictions).where(backtest_predictions.c.backtest_id == backtest_id))
            conn.execute(insert(backtest_predictions).values(backtest_id=backtest_id, rows_json=json.dumps(rows)))

    def backtest_predictions(self, backtest_id: str) -> Optional[List[Dict[str, Any]]]:
        with self._connect() as conn:
            row = conn.execute(select(backtest_predictions.c.rows_json)
                               .where(backtest_predictions.c.backtest_id == backtest_id)).first()
        return json.loads(row[0]) if row else None

    def backtests_with_predictions(self, universe: str, limit: int = 50) -> List[Dict[str, Any]]:
        query = (select(backtests.c.id, backtests.c.created_at, backtests.c.params_json)
                 .join(backtest_predictions, backtest_predictions.c.backtest_id == backtests.c.id)
                 .where(backtests.c.universe == universe).order_by(desc(backtests.c.created_at)).limit(limit))
        with self._connect() as conn:
            rows = conn.execute(query).mappings().all()
        return [{'id': r['id'], 'created_at': r['created_at'], 'params': json.loads(r['params_json'])} for r in rows]

    def get_backtest(self, backtest_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(select(backtests).where(backtests.c.id == backtest_id)).mappings().first()
        if not row:
            return None
        return {'id': row['id'], 'universe': row['universe'], 'created_at': row['created_at'],
                'demo': bool(row['demo']), 'params': json.loads(row['params_json']),
                'result': json.loads(row['result_json'])}

    def list_backtests(self, universe: str, limit: int = 50) -> List[Dict[str, Any]]:
        query = (select(backtests).where(backtests.c.universe == universe)
                 .order_by(desc(backtests.c.created_at)).limit(limit))
        with self._connect() as conn:
            rows = conn.execute(query).mappings().all()
        result = []
        for row in rows:
            data = json.loads(row['result_json'])
            result.append({'id': row['id'], 'universe': row['universe'], 'created_at': row['created_at'],
                           'demo': bool(row['demo']), 'params': json.loads(row['params_json']),
                           'settings': data.get('settings'), 'headline': data.get('headline')})
        return result

    # ----------------------------------------------------------- experiments

    def create_experiment(self, universe: str, name: str, settings: Dict[str, Any], top_n: Optional[int]) -> str:
        experiment_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(insert(experiments).values(id=experiment_id, universe=universe, name=name,
                                                    settings_json=json.dumps(settings), top_n=top_n,
                                                    status='queued', created_at=now_iso()))
        return experiment_id

    def update_experiment(self, experiment_id: str, **fields: Any) -> None:
        columns = {k: (json.dumps(v) if k.endswith('_json') else v) for k, v in fields.items()}
        unknown = set(columns) - set(experiments.c.keys())
        if unknown:
            raise ValueError(f'Unknown experiment fields: {sorted(unknown)}')
        with self._connect() as conn:
            conn.execute(update(experiments).where(experiments.c.id == experiment_id).values(**columns))

    @staticmethod
    def _experiment_dict(row: RowMapping) -> Dict[str, Any]:
        item = {k: row[k] for k in row.keys() if not k.endswith('_json')}
        item['settings'] = json.loads(row['settings_json'])
        item['development'] = json.loads(row['dev_json']) if row['dev_json'] else None
        item['lockbox'] = json.loads(row['lockbox_json']) if row['lockbox_json'] else None
        return item

    def get_experiment(self, experiment_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(select(experiments).where(experiments.c.id == experiment_id)).mappings().first()
        return self._experiment_dict(row) if row else None

    def list_experiments(self, universe: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(select(experiments).where(experiments.c.universe == universe)
                                .order_by(desc(experiments.c.created_at))).mappings().all()
        return [self._experiment_dict(r) for r in rows]

    # ------------------------------------------------------------- forecasts

    def save_forecast_batch(self, universe: str, base_date: str, summary: Dict[str, Any],
                            rows: List[Dict[str, Any]], simulated: bool = False,
                            created_at: Optional[str] = None) -> str:
        """
        Store one set of forecasts. A live set replaces an earlier live set made
        from the same prices (so each price date is scored once).
        """
        batch_id = uuid.uuid4().hex[:12]
        columns = set(forecasts.c.keys())
        fb = forecast_batches.c
        with self._connect() as conn:
            if not simulated:
                old = conn.execute(select(fb.id).where(and_(fb.universe == universe, fb.base_date == base_date,
                                                            fb.simulated == 0))).scalars().all()
                if old:
                    conn.execute(delete(forecasts).where(forecasts.c.batch_id.in_(old)))
                    conn.execute(delete(forecast_batches).where(fb.id.in_(old)))
            conn.execute(insert(forecast_batches).values(id=batch_id, universe=universe, base_date=base_date,
                                                         simulated=int(simulated), created_at=created_at or now_iso(),
                                                         summary_json=json.dumps(summary)))
            if rows:
                conn.execute(insert(forecasts), [{
                    **{k: v for k, v in r.items() if k in columns}, 'batch_id': batch_id, 'universe': universe,
                    'simulated': int(simulated)} for r in rows])
        return batch_id

    def latest_forecast_batch(self, universe: str) -> Optional[Dict[str, Any]]:
        """The newest live set of forecasts, with its rows."""
        fb = forecast_batches.c
        with self._connect() as conn:
            row = conn.execute(select(forecast_batches).where(and_(fb.universe == universe, fb.simulated == 0))
                               .order_by(desc(fb.base_date), desc(fb.created_at)).limit(1)).mappings().first()
            if row is None:
                return None
            rows = conn.execute(select(forecasts).where(forecasts.c.batch_id == row['id'])
                                .order_by(forecasts.c.symbol, forecasts.c.days)).mappings().all()
        batch = {k: row[k] for k in row.keys() if k != 'summary_json'}
        batch['summary'] = json.loads(row['summary_json'])
        batch['forecasts'] = [dict(r) for r in rows]
        return batch

    def open_forecasts(self, universe: str) -> List[Dict[str, Any]]:
        """Live forecasts whose outcome has not been recorded yet."""
        with self._connect() as conn:
            rows = conn.execute(select(forecasts).where(and_(
                forecasts.c.universe == universe, forecasts.c.evaluated_at.is_(None),
                forecasts.c.simulated == 0))).mappings().all()
        return [dict(r) for r in rows]

    def record_forecast_outcome(self, batch_id: str, symbol: str, horizon: str, target_date: str,
                                realized_price: float, inside_50: int, inside_90: int) -> None:
        with self._connect() as conn:
            conn.execute(update(forecasts).where(and_(forecasts.c.batch_id == batch_id,
                                                      forecasts.c.symbol == symbol,
                                                      forecasts.c.horizon == horizon))
                         .values(target_date=target_date, realized_price=realized_price, inside_50=inside_50,
                                 inside_90=inside_90, evaluated_at=now_iso()))

    def scored_forecasts(self, universe: str, simulated: Optional[bool] = None) -> List[Dict[str, Any]]:
        """Forecasts with a recorded outcome (the fields needed for reliability)."""
        f = forecasts.c
        query = select(f.symbol, f.horizon, f.base_date, f.target_date, f.inside_50, f.inside_90, f.simulated) \
            .where(and_(f.universe == universe, f.inside_90.is_not(None)))
        if simulated is not None:
            query = query.where(f.simulated == int(simulated))
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(query.order_by(f.base_date)).mappings().all()]

    def has_forecasts(self, universe: str) -> bool:
        with self._connect() as conn:
            return conn.execute(select(forecast_batches.c.id).where(forecast_batches.c.universe == universe)
                                .limit(1)).first() is not None

    # ------------------------------------------------------------------ jobs

    def insert_job(self, row: Dict[str, Any]) -> bool:
        """Insert a job row; False when an active job of the same kind and universe already exists."""
        from sqlalchemy.exc import IntegrityError
        try:
            with self._connect() as conn:
                conn.execute(insert(jobs).values(**row))
            return True
        except IntegrityError:
            return False

    def update_job(self, job_id: str, **fields: Any) -> None:
        with self._connect() as conn:
            conn.execute(update(jobs).where(jobs.c.id == job_id).values(**fields))

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
        return dict(row) if row else None

    def active_job(self, kind: str, universe: str) -> Optional[Dict[str, Any]]:
        query = (select(jobs).where(and_(jobs.c.kind == kind, jobs.c.universe == universe,
                                         jobs.c.status.in_(('queued', 'running'))))
                 .order_by(desc(jobs.c.created_at)).limit(1))
        with self._connect() as conn:
            row = conn.execute(query).mappings().first()
        return dict(row) if row else None

    def list_jobs(self, universe: Optional[str] = None, limit: int = 50,
                  statuses: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        query = select(jobs)
        if universe:
            query = query.where(jobs.c.universe == universe)
        if statuses:
            query = query.where(jobs.c.status.in_(statuses))
        with self._connect() as conn:
            rows = conn.execute(query.order_by(desc(jobs.c.created_at)).limit(limit)).mappings().all()
        return [dict(r) for r in rows]

    def job_counts(self) -> List[Dict[str, Any]]:
        """Jobs by kind, universe and status (for metrics)."""
        query = select(jobs.c.kind, jobs.c.universe, jobs.c.status, func.count().label('n')) \
            .group_by(jobs.c.kind, jobs.c.universe, jobs.c.status)
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(query).mappings().all()]


SEVERITY_RANK = {'info': 0, 'warning': 1, 'critical': 2}


def _notification_dict(row: RowMapping) -> Dict[str, Any]:
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
        from sqlalchemy.exc import IntegrityError

        created = created_at or now_iso()
        n = notifications.c
        try:
            with self.store._connect() as conn:
                if conn.execute(select(n.id).where(n.dedupe_key == dedupe_key)).first():
                    return None
                since = (datetime.fromisoformat(created) - timedelta(hours=cooldown_hours)).isoformat(timespec='seconds')
                recent = conn.execute(select(n.severity).where(and_(
                    n.universe == universe, n.type == signal['type'],
                    n.symbol.is_not_distinct_from(signal.get('symbol')), n.created_at >= since))).scalars().all()
                if recent and max(SEVERITY_RANK[r] for r in recent) >= SEVERITY_RANK[signal['severity']]:
                    return None
                result = conn.execute(insert(notifications).values(
                    universe=universe, type=signal['type'], severity=signal['severity'], symbol=signal.get('symbol'),
                    title=signal['title'], body=signal['body'], data_json=json.dumps(signal.get('data', {})),
                    event_date=signal['event_date'], session=session, created_at=created, dedupe_key=dedupe_key))
                return int(result.inserted_primary_key[0])
        except IntegrityError:  # another process stored the same event at the same moment
            return None

    def get(self, notification_id: int) -> Optional[Dict[str, Any]]:
        with self.store._connect() as conn:
            row = conn.execute(select(notifications).where(notifications.c.id == notification_id)).mappings().first()
        return _notification_dict(row) if row else None

    def list(self, universe: Optional[str] = None, unread_only: bool = False, limit: int = 100) -> List[Dict[str, Any]]:
        n = notifications.c
        query = select(notifications)
        if universe:
            query = query.where(n.universe == universe)
        if unread_only:
            query = query.where(n.read_at.is_(None))
        query = query.order_by(desc(n.event_date), desc(n.created_at), desc(n.id)).limit(limit)
        with self.store._connect() as conn:
            rows = conn.execute(query).mappings().all()
        return [_notification_dict(r) for r in rows]

    def unread_counts(self) -> Dict[str, Dict[str, int]]:
        n = notifications.c
        query = select(n.universe, n.severity, func.count().label('n')).where(n.read_at.is_(None)) \
            .group_by(n.universe, n.severity)
        with self.store._connect() as conn:
            rows = conn.execute(query).mappings().all()
        counts: Dict[str, Dict[str, int]] = {}
        for r in rows:
            entry = counts.setdefault(r['universe'], {'total': 0, 'critical': 0, 'warning': 0, 'info': 0})
            entry[r['severity']] = r['n']
            entry['total'] += r['n']
        return counts

    def mark_read(self, notification_id: int) -> bool:
        n = notifications.c
        with self.store._connect() as conn:
            conn.execute(update(notifications).where(and_(n.id == notification_id, n.read_at.is_(None)))
                         .values(read_at=now_iso()))
            return conn.execute(select(n.id).where(n.id == notification_id)).first() is not None

    def mark_all_read(self, universe: Optional[str] = None) -> int:
        n = notifications.c
        query = update(notifications).where(n.read_at.is_(None)).values(read_at=now_iso())
        if universe:
            query = query.where(n.universe == universe)
        with self.store._connect() as conn:
            return conn.execute(query).rowcount
