# 6. Predict a relative return over 5 days

- **Status:** accepted, November 2026

## Context

On any given day most assets move with the market, and no asset-level feature
predicts the market. Next-day direction is close to random.

## Decision

The target is whether an asset beats its universe's average return over the next
*h* days (default 5): the return minus the equal-weight universe average.
Subtracting the average removes the unpredictable common move and leaves what a
ranking can use. It also balances the classes (about half beat the average) and
lets signals persist longer than one day.

## Consequences

- "Beat the field" only makes sense inside one universe
  ([ADR 10](0010-separate-pipelines-per-universe.md)).
- Details: `docs/design/analysis.md`, section 6.
