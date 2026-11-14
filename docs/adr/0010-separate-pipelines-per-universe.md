# 10. Keep stocks and crypto in separate pipelines

- **Status:** accepted, November 2026

## Context

The two asset classes have different calendars (252 vs 365 days a year),
volatility and drivers, and "beat the field" only makes sense within one market.

## Decision

Each universe has its own pipeline instance, model file (`data/models/{universe}.joblib`),
settings, stored analyses and model registry entries. Nothing learned on one
affects the other. Both share the indicator set, scoring rules, model
architecture and backtest engine, which keeps results comparable and the code small.

## Consequences

- A new universe is a subclass of `AssetRanker` plus a config entry
  (`docs/design/reference.md`, section 19).
