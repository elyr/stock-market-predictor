# 7. Rank IC is the headline metric

- **Status:** accepted, November 2026

## Context

Accuracy is misleading near 50%, and the product ranks assets rather than
calling direction. For short-horizon returns an IC of 0.03-0.05 is good;
next-day direction accuracy above 60% almost always means a bug.

## Decision

The headline metric is the out-of-sample rank information coefficient with a
t-statistic. Outcomes over *h* days overlap from day to day, so t-statistics on
daily ICs count independent periods (`information_coefficient(..., overlap=h)`).
Every verdict shown to the user ("Indistinguishable from luck", "Some evidence
of skill") comes from it.

## Consequences

- A model change must be tested in both directions: it finds the planted signal
  and finds nothing on a market without one.
- Details: `docs/design/evaluation.md`.
