# 12. Run analyses as background jobs and poll

- **Status:** accepted, November 2026

## Context

Training takes minutes, so a synchronous request would time out.

## Decision

Starting an analysis returns a job (202). The UI polls `GET /api/jobs/{id}`.
Jobs are kept in the database and run in-process or by Redis workers, with one
lock per universe, so a stock job and a crypto job run in parallel while two on
the same universe queue. Starting an analysis that is already running returns
the existing job.

## Consequences

- Details: `docs/design/operations.md`, section 11e.
