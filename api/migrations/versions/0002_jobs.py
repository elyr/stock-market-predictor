"""Background jobs in the database, so every server process and worker sees them.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from api.db import ACTIVE_JOB_INDEX, jobs

    jobs.create(op.get_bind())
    # At most one queued or running job of a kind per universe (when the job asks for it)
    active = sa.text("status IN ('queued', 'running') AND dedupe = 1")
    op.create_index(ACTIVE_JOB_INDEX, 'jobs', ['kind', 'universe'], unique=True,
                    sqlite_where=active, postgresql_where=active)


def downgrade() -> None:
    from api.db import ACTIVE_JOB_INDEX

    op.drop_index(ACTIVE_JOB_INDEX, table_name='jobs')
    op.drop_table('jobs')
