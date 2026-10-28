# Ledger: development guidelines

Ledger ranks US stocks and crypto by the probability of beating their universe over the next few days,
with out-of-sample evidence, backtests and a track record. See docs/ARCHITECTURE.md.

## Layout
- `src/`: Python prediction core (pipelines, models, backtest). Works standalone via `src/cli.py`.
- `api/`: FastAPI server (jobs, SQLite store, JSON endpoints under `/api/{stocks|crypto}/...`).
- `frontend/`: Angular 22 app, standalone components and signals; two dashboards sharing page components.

## Rules
- Never use future information: features at date t use data up to t; training rows must have labels known at decision time.
- Stocks and crypto stay separate: separate pipeline instances, models, settings and stored runs.
- Evaluate with chronological, purged splits; report rank IC with t-statistics rather than raw accuracy.
- Keep tests offline: use `SyntheticDataCollector`; mark live-data tests with `@pytest.mark.network`.
- Python: type hints and docstrings, PEP 8. Frontend: signals for state, no UI kit, design tokens in `styles.scss`.
