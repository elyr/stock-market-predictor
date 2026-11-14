# 13. Use SQLite by default and PostgreSQL when deployed

- **Status:** accepted, November 2026

## Context

A single user's history fits in one file with zero setup, but several server
processes need a shared database.

## Decision

SQLite is the default store for local and demo use. PostgreSQL is used when
`DATABASE_URL` is set (the Kubernetes `--postgres` profile). Store code, schema
and migrations must work on both. Jobs are rows in the same database. They run
in the server by default; the scaled shape (PostgreSQL) adds a Redis queue,
which carries only job ids, and worker processes, so it needs a Redis service
as well as PostgreSQL.

## Consequences

- Schema changes need an Alembic migration and an entry in `TABLES`.
- Which run path uses which shape: the table in `docs/GUIDE.md` ("Where the data lives").
- Details: `docs/design/operations.md`, section 11e.
