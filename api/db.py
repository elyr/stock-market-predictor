"""
Database access: the schema, the engine for SQLite or PostgreSQL, and
migrations.

SQLite (a file next to the app) is the default and needs nothing installed.
PostgreSQL is used when ``DATABASE_URL`` is set, e.g.
``postgresql+psycopg://ledger:secret@postgres:5432/ledger``; it lets several
server processes share one database (see docs/ARCHITECTURE.md, §12a).

The schema is defined once here with SQLAlchemy Core and changed only through
Alembic migrations (``api/migrations``), applied at startup by ``migrate``.
"""

import logging
import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import (Column, Float, ForeignKey, Index, Integer, MetaData, String, Table, Text, create_engine,
                        event, text)
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

metadata = MetaData()

runs = Table(
    'runs', metadata,
    Column('id', String(32), primary_key=True),
    Column('universe', String(16), nullable=False),
    Column('created_at', String(40), nullable=False),
    Column('data_date', String(10), nullable=False),
    Column('horizon', Integer, nullable=False),
    Column('top_n', Integer, nullable=False),
    Column('demo', Integer, nullable=False, server_default='0'),
    Column('simulated', Integer, nullable=False, server_default='0'),
    Column('summary_json', Text, nullable=False),
    Column('evaluated_at', String(40)),
    Column('exit_date', String(10)),
    Column('portfolio_return', Float),
    Column('universe_return', Float),
    Column('excess_return', Float),
    Column('rank_ic', Float),
    Index('idx_runs_universe', 'universe', 'data_date'),
)

predictions = Table(
    'predictions', metadata,
    Column('run_id', String(32), ForeignKey('runs.id', ondelete='CASCADE'), nullable=False, primary_key=True),
    Column('symbol', String(32), nullable=False, primary_key=True),
    Column('rank', Integer, nullable=False),
    Column('picked', Integer, nullable=False),
    Column('weight', Float),
    Column('composite_score', Float),
    Column('ml_probability', Float),
    Column('entry_price', Float),
    Column('realized_return', Float),
    Column('payload_json', Text, nullable=False),
)

notifications = Table(
    'notifications', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('universe', String(16), nullable=False),
    Column('type', String(32), nullable=False),
    Column('severity', String(16), nullable=False),
    Column('symbol', String(32)),
    Column('title', Text, nullable=False),
    Column('body', Text, nullable=False),
    Column('data_json', Text, nullable=False),
    Column('event_date', String(10), nullable=False),
    Column('session', String(16)),
    Column('created_at', String(40), nullable=False),
    Column('read_at', String(40)),
    Column('dedupe_key', String(200), nullable=False, unique=True),
    Index('idx_notifications_universe', 'universe', 'created_at'),
)

backtest_predictions = Table(
    'backtest_predictions', metadata,
    Column('backtest_id', String(32), primary_key=True),
    Column('rows_json', Text, nullable=False),
)

experiments = Table(
    'experiments', metadata,
    Column('id', String(32), primary_key=True),
    Column('universe', String(16), nullable=False),
    Column('name', String(200), nullable=False),
    Column('settings_json', Text, nullable=False),
    Column('top_n', Integer),
    Column('status', String(16), nullable=False),
    Column('error', Text),
    Column('created_at', String(40), nullable=False),
    Column('dev_backtest_id', String(32)),
    Column('dev_json', Text),
    Column('lockbox_backtest_id', String(32)),
    Column('lockbox_json', Text),
    Column('lockbox_checked_at', String(40)),
)

backtests = Table(
    'backtests', metadata,
    Column('id', String(32), primary_key=True),
    Column('universe', String(16), nullable=False),
    Column('created_at', String(40), nullable=False),
    Column('demo', Integer, nullable=False, server_default='0'),
    Column('params_json', Text, nullable=False),
    Column('result_json', Text, nullable=False),
)

jobs = Table(
    'jobs', metadata,
    Column('id', String(32), primary_key=True),
    Column('kind', String(32), nullable=False),
    Column('universe', String(16), nullable=False),
    Column('status', String(16), nullable=False),
    Column('message', Text, nullable=False),
    Column('params_json', Text, nullable=False),
    # 1: at most one queued or running job of this kind and universe (enforced by an index)
    Column('dedupe', Integer, nullable=False, server_default='1'),
    Column('created_at', String(40), nullable=False),
    Column('started_at', String(40)),
    Column('finished_at', String(40)),
    Column('result_json', Text),
    Column('error', Text),
    Column('worker', String(200)),
    Index('idx_jobs_universe', 'universe', 'created_at'),
)

forecast_batches = Table(
    'forecast_batches', metadata,
    Column('id', String(32), primary_key=True),
    Column('universe', String(16), nullable=False),
    Column('created_at', String(40), nullable=False),
    Column('base_date', String(10), nullable=False),
    Column('simulated', Integer, nullable=False, server_default='0'),
    Column('summary_json', Text, nullable=False),
    Index('idx_forecast_batches_universe', 'universe', 'base_date'),
)

forecasts = Table(
    'forecasts', metadata,
    Column('batch_id', String(32), ForeignKey('forecast_batches.id', ondelete='CASCADE'), primary_key=True),
    Column('symbol', String(32), primary_key=True),
    Column('horizon', String(8), primary_key=True),
    Column('universe', String(16), nullable=False),
    Column('days', Integer, nullable=False),
    Column('base_date', String(10), nullable=False),
    Column('base_price', Float, nullable=False),
    Column('sigma', Float, nullable=False),
    Column('q05', Float, nullable=False),
    Column('q25', Float, nullable=False),
    Column('q50', Float, nullable=False),
    Column('q75', Float, nullable=False),
    Column('q95', Float, nullable=False),
    # 1: made by replaying history (demo), not before the outcome existed
    Column('simulated', Integer, nullable=False, server_default='0'),
    Column('target_date', String(10)),
    Column('realized_price', Float),
    Column('inside_50', Integer),
    Column('inside_90', Integer),
    Column('evaluated_at', String(40)),
    Index('idx_forecasts_open', 'universe', 'evaluated_at'),
    Index('idx_forecasts_symbol', 'universe', 'symbol', 'base_date'),
)

# Tables in an order that respects references (backups restore them in this order)
TABLES = [runs, predictions, notifications, backtests, backtest_predictions, experiments, jobs,
          forecast_batches, forecasts]

ACTIVE_JOB_INDEX = 'uq_jobs_active'
MIGRATION_LOCK = 72_700_901  # PostgreSQL advisory lock id while migrating


def database_url(database_path: str, url: Optional[str] = None) -> str:
    """``DATABASE_URL`` if given, else the SQLite file at ``database_path``."""
    url = url or os.environ.get('DATABASE_URL', '').strip()
    if url:
        if url.startswith('postgres://') or url.startswith('postgresql://'):
            # The psycopg 3 driver, whatever form the URL comes in
            url = 'postgresql+psycopg://' + url.split('://', 1)[1]
        return url
    directory = os.path.dirname(database_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    return f'sqlite:///{os.path.abspath(database_path)}'


def is_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == 'sqlite'


def make_engine(url: str) -> Engine:
    if url.startswith('sqlite'):
        engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30},
                               pool_pre_ping=True)

        @event.listens_for(engine, 'connect')
        def _sqlite_pragmas(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys = ON')
            cursor.execute('PRAGMA busy_timeout = 30000')
            cursor.close()
        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=1800)


def safe_url(url: str) -> str:
    """The URL without its password, for logs and the API."""
    from sqlalchemy.engine import make_url
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return url.split('@')[-1]


@contextmanager
def migration_lock(connection: Connection) -> Iterator[None]:
    """On PostgreSQL, only one process migrates at a time (server replicas start together)."""
    if connection.dialect.name == 'postgresql':
        connection.execute(text('SELECT pg_advisory_lock(:id)'), {'id': MIGRATION_LOCK})
        try:
            yield
        finally:
            connection.execute(text('SELECT pg_advisory_unlock(:id)'), {'id': MIGRATION_LOCK})
    else:
        yield


def migrate(engine: Engine) -> str:
    """Bring the schema up to date with Alembic; returns the revision now in place."""
    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext

    config = Config()
    config.set_main_option('script_location', os.path.join(os.path.dirname(__file__), 'migrations'))
    with engine.connect() as connection:
        with migration_lock(connection):
            connection.commit()  # the lock lives on the session; migrations run in their own transaction
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
            connection.commit()
            revision = MigrationContext.configure(connection).get_current_revision()
    logger.info(f'Database schema at revision {revision} ({safe_url(str(engine.url))})')
    return revision
