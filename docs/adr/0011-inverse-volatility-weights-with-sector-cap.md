# 11. Weight picks by inverse volatility with a sector cap

- **Status:** accepted, November 2026

## Context

Equal weights let one volatile asset or one sector dominate the result.

## Decision

The portfolio takes assets in composite order, skips any that would exceed the
per-sector cap (3 for stocks, none for crypto), and weights the rest in
proportion to 1 / volatility so each contributes similar risk.

## Consequences

- Details: `docs/design/analysis.md`, section 7; code in `src/prediction/portfolio.py`.
