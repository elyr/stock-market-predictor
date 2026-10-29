"""The original schema: runs, predictions, notifications, backtests, experiments.

Databases created before migrations existed already have these tables; they
are left as they are and only marked as migrated.

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

TABLES = ('runs', 'predictions', 'notifications', 'backtest_predictions', 'experiments', 'backtests')


def upgrade() -> None:
    from api.db import metadata

    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for name in TABLES:
        if name not in existing:
            metadata.tables[name].create(bind)


def downgrade() -> None:
    for name in reversed(TABLES):
        op.drop_table(name)
