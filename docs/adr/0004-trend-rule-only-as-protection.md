# 4. Offer the trend rule only as protection, behind an accuracy bar

- **Status:** accepted, November 2026

## Context

The trend rule holds an asset only while its price is above at least 2 of its
50-, 100- and 200-day averages. Research on real prices
(`docs/research/2026-11-predictor-review.md`, `2026-11-large-universe.md`) found
that it does not predict returns: on stocks it cut the return from 18% to 8% a
year, on coins it kept the return (52% vs 52%) and cut the worst drop (-72% vs
-89%). It limits deep falls; it is not a signal.

## Decision

The rule is offered only as protection, and only in a universe whose own history
shows it cuts the worst drop without giving up return. The bar is in
`signals.trend` in `config/config.yaml`: at least 750 days of history, a worst
drop at least 25% smaller than holding's, and a return at most 2 points a year
below holding's. Nothing is hard-coded per universe, and the bar and window are
not tuned to make a universe pass. Alerts (`trend_exit`, `trend_enter`) are
named protection alerts, always state the rule's record and end with "This rule
limits deep falls. It does not predict returns." 

## Consequences

- Stocks are expected to fail the bar and coins to pass it narrowly; the
  result depends on the window, so protection alerts stop by themselves when a
  record no longer meets the bar.
- A scan fetches 5 years of prices instead of 6 months while the rule is enabled.
- Details: `docs/design/alerts.md`, section 11a; code in `src/signals/trend.py`.
