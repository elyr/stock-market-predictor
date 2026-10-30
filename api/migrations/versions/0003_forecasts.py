"""Price range forecasts and their outcomes.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from api.db import forecast_batches, forecasts

    bind = op.get_bind()
    forecast_batches.create(bind)
    forecasts.create(bind)


def downgrade() -> None:
    op.drop_table('forecasts')
    op.drop_table('forecast_batches')
