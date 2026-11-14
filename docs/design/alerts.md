# Market signals, alerts and the trend rule

What raises an alert and how the trend rule is offered as protection. Part of the [architecture](../ARCHITECTURE.md); section numbers (§) are unchanged and indexed in the architecture.

## 11a. Market signals and alerts

The detector does not predict; it notices what is unusual *for each asset*,
shortly after it happens, and raises an in-app alert.

| Alert | Rule (defaults) | Scan |
|---|---|---|
| Unusual move | today's return minus the universe average, ≥ 3 standard deviations of that difference over the last 60 bars (critical at 5) | open and close |
| Volume spike | volume ≥ 3× its 20-bar average without an unusual move (critical at 5×); folded into the move alert when both happen | close |
| Opening gap | open vs previous close ≥ 3 standard deviations and ≥ 2% (stocks) or 4% (crypto) | open and close |
| Market-wide move | the universe's average return ≥ 3 standard deviations of its own history, or ≥ 85% of assets down on a weak day | open and close |
| Protection (trend rule) | an asset's state changes on the latest bar, in a universe whose record passes the bar (below) | close |
| Portfolio change | a new analysis adds or drops picks | after each analysis |
| Volatility rising | a holding's volatility model says ≥ 70% chance of more volatility and forecasts ≥ 1.2× today's level | after each analysis |

Removing the universe average from each asset's move means a market-wide drop
produces one market alert, not one alert per asset.

**Protection alerts (the trend rule).** Holding an asset only while its price is
above at least 2 of its 50-, 100- and 200-day averages did not predict returns
in the research (`docs/research/2026-11-large-universe.md`): it cut returns by
more than half on stocks and, on coins, kept the return while cutting the worst
drop. So it is offered only as protection, and only where a universe's own
record supports that.

- *State.* `trend_state(close)` is 1 while the close is above at least 2 of the
  3 averages. The state on day *t* uses closes up to *t* (tested).
- *Record.* `rule_record(closes, cost_bps)` replays the rule on the universe's
  own history, equally weighted over the assets that have a state. The state at
  the close of day *t* is acted on at the close of *t*+1, with a cost on every
  change (`signals.trend.cost_bps`: stocks 5, crypto 15). It reports return per
  year and worst drop for the rule and for holding, time in the market, trades
  per asset per year, and the first and last date.
- *Accuracy bar* (`signals.trend` in config.yaml). A universe passes only if its
  record has at least `min_history_days` (750) days, the rule's worst drop is at
  least `min_drop_improvement` (25%) smaller than holding's, and the rule's
  return per year is at most `max_return_shortfall` (2 points) below holding's.
  Nothing is hard-coded per universe: on real data stocks are expected to fail
  and coins to pass.
- *Alerts.* Only in a universe that passes. When an asset's state changes on the
  latest bar: `trend_exit` (warning, "move to cash (protection)") or
  `trend_enter` (info, "trend is back up"). The body states the record in plain
  words and ends with "This rule limits deep falls. It does not predict
  returns." In a universe that fails, no trend alert is sent.
- *Where it passes.* On real prices in November 2026, with the default bar,
  coins pass narrowly on the 5-year window the scan uses: the rule returned about
  9% a year with a worst drop of 52%, against 2% a year and 72% for holding, a
  28% smaller drop against the 25% needed. The result depends on the window: over
  10 years the improvement is 18% and coins fail. Stocks fail on return over 5
  years (the rule about 7% a year, holding about 18%), as the research expected.
  Protection alerts stop by themselves in any universe whose record no longer
  meets the bar; the bar and the window are not tuned to make coins pass.
- *Cost.* The record needs years of prices, so a scan fetches 5 years instead of
  6 months while the rule is enabled. It is computed once per set of prices and
  cached on the universe's detector. `GET /api/{universe}/trend` returns the
  record, the verdict with its reasons and each asset's state with the date it
  last changed.

**Schedule.** Two scans a day in New York time: 09:45 (after the open: gaps
and early moves) and 16:15 (after the close: everything). Stocks are scanned on
weekdays, crypto every day at the same times. Market holidays are not special-
cased: a holiday scan sees the previous day's bar, which deduplication ignores.

**Noise control.** An event is stored once per asset, type and day (dedupe
key), and an alert of the same type for the same asset is suppressed for 12
hours unless it is more severe. On realistic data about 1% of asset-days
trigger an alert, so a 100-stock scan typically raises one or two.

**Delivery.** Notifications are stored in SQLite and shown in the app (Alerts
page, unread badges). `Notifier` hands each new notification to any extra
channels; none are configured yet. Adding Telegram, email or Discord means
implementing `NotificationChannel.deliver` and passing it to `Notifier`.
