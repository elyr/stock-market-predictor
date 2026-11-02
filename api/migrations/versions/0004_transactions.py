"""Your own transactions (My portfolio).

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from api.db import transactions

    transactions.create(op.get_bind())


def downgrade() -> None:
    op.drop_table('transactions')
