"""Alembic environment: migrations run on the connection given by api.db.migrate."""

from alembic import context

from api.db import metadata

connection = context.config.attributes.get('connection')
if connection is None:
    raise SystemExit('Run migrations through api.db.migrate (or python -m api.migrate)')

context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
