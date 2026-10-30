# Ledger: instructions for GitHub Copilot

The full instructions for coding agents are in [AGENTS.md](../AGENTS.md) at the
repository root: project map, commands, the rules the results depend on,
conventions, workflow and known pitfalls. Read it first.

The rules reviews check first:
- Never use future information: features at date t use data up to t; targets are excluded from features by name; training labels must be known at decision time.
- Stocks and crypto stay separate: separate pipelines, models, settings and stored runs.
- Evaluate with chronological, purged splits; report rank IC with t-statistics; rank on the model's raw score, never the calibrated probability.
- Keep tests offline with `SyntheticDataCollector`; a model change must find the planted signal and find nothing without it.
- Frontend: standalone components and signals, design tokens in `styles.scss`, help text through `<app-hint term="…">` and `core/glossary.ts`.
