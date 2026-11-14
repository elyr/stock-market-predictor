# 5. No buy or sell alerts on stocks

- **Status:** accepted, November 2026

## Context

The research on real data (`docs/research/2026-11-predictor-review.md`) tested
four families of signals on the app's 107 large stocks: the current model,
holding for 21 days or 20 picks, momentum or low volatility alone, and the trend
rule, plus earnings surprises. None passed after costs. The model had no
measurable skill (alpha 0.9% a year, t = 0.12), and the picks were mostly
high-beta, high-volatility names, which is market risk.

## Decision

Ledger sends no buy or sell alerts for stocks. Market signals (unusual moves,
volume spikes, gaps, broad selloffs, changed picks) report what happened and do
not predict. The only directional alert is the protection alert from the trend
rule, and only where a universe passes the bar
([ADR 4](0004-trend-rule-only-as-protection.md)). The four families are not
re-tested on this universe.

## Consequences

- Stock alerts may be added only for rules that pass the planned large-universe
  test (about 1,500 companies, realistic costs, a held-back test period).
- The README and the UI say plainly that no signal that predicts returns was found.
