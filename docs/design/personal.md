# Price ranges, your portfolio and the weekly brief

The Forecast page and the personal pages. Part of the [architecture](../ARCHITECTURE.md); section numbers (§) are unchanged and indexed in the architecture.

## 11f. Price ranges (Forecast)

A single predicted price would mislead: over a day or a week the expected move
is tiny compared with the noise, so the honest point forecast is today's price.
The Forecast page shows **ranges** instead (`src/models/forecast.py`):

- **Volatility at each date**: an exponentially weighted volatility of daily
  log returns (decay 0.94), blended 70/30 with the one-year volatility, using
  only prices up to that date.
- **Standardized moves**: each past move over the horizon divided by
  `volatility × √days`. Their empirical quantiles, pooled over the universe and
  centred on zero, set the 5%, 15%, 25%, 75%, 85% and 95% levels: the **50%,
  70% and 90% ranges**. Fat tails are kept, and past drift is not treated as a
  forecast.
- **Horizons**:
  - stocks: the next session, 3 sessions and 5 sessions;
  - crypto, which trades every day: 24 hours, 3 days and 7 days;
  - `universes.<u>.forecast_horizons` in the config adds or replaces horizons by key, for example `{month: 21}`.
- **Pages**: the **Next 3 days** page shows each asset's 70% range for the
  3-day horizon (7 times in 10), how often such ranges held, and how they are
  computed, in plain steps. Forecasts stored before the 70% range existed
  (migration 0005) are scored on the 50% and 90% ranges only.
- **Reliability** comes from three places:
  - When fitting, the quantiles come from earlier dates, and coverage is
    measured on the last quarter of dates after a purge gap.
  - Every live forecast is stored (`forecast_batches`, `forecasts`) and scored
    once its window has passed.
  - A new demo dashboard gets a replayed history, marked as simulated.

  The page, Track record, `/metrics` (`ledger_forecast_coverage`) and the
  `LedgerForecastRangesUnreliable` alert all use these scores.
- **When**: after every analysis, and on demand (`POST /api/{universe}/forecast`,
  the `forecast` job).

---

## 11g. My portfolio

The **My portfolio** page follows what you actually own. Everything is derived from
the trades you record (`transactions` table, migration 0004), so nothing is lost
and the history can always be replayed (`src/personal/portfolio.py`).

- **Holdings** use the average-cost method:
  - a buy adds to the quantity and to the cost, fees included;
  - a sale realises the gain on the shares sold at the average cost, which stays unchanged;
  - a sale larger than what was held on its date is refused, and so is deleting a buy that a later sale needs.
- **History.** The value is rebuilt every day since the first trade from daily
  closes. The benchmark receives *the same cash flows on the same days*: the
  average stock of the list for stocks, Bitcoin for crypto. "Compared with the
  benchmark" is therefore unaffected by when money went in or out. It answers
  "did my choices beat simply buying the market?".
- **Risk.** Yearly volatility comes from the holdings' last 120 daily returns
  and their correlations, turned into a word (calm, moderate, high, very high)
  and a likely range for next week's value (normal approximation, roughly 9
  times in 10).
- **Warnings** come from your rules (`universes.<u>.risk` in `config.yaml`:
  largest share in one holding or sector, yearly volatility, minimum number of
  holdings) and from the models (volatility likely to rise; ranked in the bottom
  fifth, explicitly not a sell signal). Each is one plain sentence saying what
  is wrong and what to consider.
- Each holding shows the model's view (chance to beat the field, rank) and
  its next-week 90% range from the Forecast.

Stocks and crypto keep separate portfolios, as for everything else.

---

## 11h. Weekly brief

The **Weekly brief** (`src/personal/brief.py`) turns Ledger's numbers into a
page a non-expert can read in two minutes. It uses fixed rules, not a language
model, so every sentence comes from a number shown elsewhere in the app and
reads the same way every week.

| Section | Built from |
|---|---|
| The market | the week's return of every asset in the universe (average, share up, best and worst three), and last month's daily swings against the previous three months |
| Your portfolio | My portfolio: the week's change excluding money added or taken out, the comparison with the benchmark, risk level and next week's likely value, and the warnings |
| Is the model working? | the latest analysis's out-of-sample rank IC and t-statistic, and the live track record. Under 8 scored periods, it says it is too early to judge |
| Picks | the top of the latest ranking with next week's 90% ranges. It says plainly that they are a watch list unless the model has proven itself on live data |
| Alerts | this week's notifications, those on assets you hold first |

**What to do** comes first on the page. In order, it can say:
1. run a new analysis, when the latest is more than 3 days old;
2. bring oversized positions back under your limit;
3. fix the next most important rule that is broken;
4. look at alerts on assets you hold;
5. don't trade on the picks alone, while the model is unproven;
6. otherwise, *nothing to do*: staying put is a decision too.

`GET /api/{universe}/brief.md` returns the same brief as Markdown.
