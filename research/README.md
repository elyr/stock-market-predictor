# Research scripts

One-off scripts behind `docs/research/2026-11-predictor-review.md`. They use
real market data (Yahoo Finance), are not part of the app or its tests, and
cache downloads as `*.pkl` in this folder (ignored by git).

Run from the repository root, in this order the first time:

| Script | What it does | Needs first |
|---|---|---|
| `real_backtest.py <universe> 10y <days> [cost_bps]` | The app's own backtester on real prices; writes the `<universe>_10y.pkl` cache | |
| `feature_ic.py <universe>` | Rank IC of each model input at 1, 5 and 21 days | `real_backtest.py` |
| `variants.py <universe> <cost_bps>` | Fast walk-forward test of picking variants, with beta and alpha | `real_backtest.py` |
| `fetch_alt.py` | Long ETF and coin histories | |
| `trend.py`, `trend_robust.py`, `rule23.py` | Trend rules on coins, ETFs and both universes | `fetch_alt.py`, `real_backtest.py` |
| `fetch_earnings.py`, `pead.py` | Earnings history and the post-earnings event study | `real_backtest.py stocks` |
