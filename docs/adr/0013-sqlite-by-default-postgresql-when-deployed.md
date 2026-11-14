# 13. Use SQLite by default and PostgreSQL when deployed

- **Status:** accepted, November 2026

## Context

A single user's history fits in one file with zero setup, but several server
processes need a shared database.

## Decision

SQLite is the default store for local and demo use. PostgreSQL is used when
`DATABASE_URL` is set (the Kubernetes `--postgres` profile). Store code, schema
and migrations must work on both.

## Consequences

- Schema changes need an Alembic migration and an entry in `TABLES`.
- Details: `docs/design/operations.md`, section 11e.
