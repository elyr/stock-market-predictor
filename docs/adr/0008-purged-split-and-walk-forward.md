# 8. Use a purged chronological split and walk-forward retraining

- **Status:** accepted, November 2026

## Context

Labels over *h* days overlap in time, so a random split, or a split with no gap,
leaks the future into training.

## Decision

Splits are chronological with a purge gap equal to the horizon. Backtests are
walk-forward and retrain at each step. Training rows need labels that are known
at decision time. A "scramble the future" test checks that changing every price
after a cutoff leaves earlier picks unchanged.

## Consequences

- Do not tune on the lockbox period; experiments check a winner once on it.
- Details: `docs/design/analysis.md` (section 8) and `docs/design/evaluation.md`.
