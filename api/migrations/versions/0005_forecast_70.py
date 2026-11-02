"""The 70% price range: q15, q85 and inside_70 on forecasts.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

COLUMNS = (('q15', sa.Float()), ('q85', sa.Float()), ('inside_70', sa.Integer()))


def upgrade() -> None:
    # 0003 creates the table from the current definition, so a new database already has them
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('forecasts')}
    for name, kind in COLUMNS:
        if name not in existing:
            op.add_column('forecasts', sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('forecasts') as batch:
        for name, _ in COLUMNS:
            batch.drop_column(name)
