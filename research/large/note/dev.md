## Development results (to 2024-11-10)

**128 tests were run** (108 stock rows, 20 coin rows: every signal × size tier × horizon that had enough
periods; the small-coin tier and some tiers of the trend rule had too few observations and are absent).
**None passed the bar** (positive, t ≥ 3). The largest t in development was 1.96 (12-1 month momentum on
large stocks, 15.5% alpha a year); the largest on coins 1.61 (low volatility, large coins). Both are within what luck
gives across 128 tests.

What stands out:

- **Stocks, ridge model (A):** negative alpha at 5 days (−12.6% a year, t = −2.6 on all assets; −27% on small stocks, t = −5.5) and zero at 21 days. IC is 0.
  The model's picks were no better than the average stock and cost more to trade.
- **Stocks, single inputs (B):** momentum is the only positive one (large stocks 15.5% a year, t = 2.0, not enough). Low volatility is a lower-beta
  bet with no alpha. 5-day reversal loses heavily after costs because it turns over about 90% of the picks each week.
- **Stocks, trend rule (C):** rule 3.9% a year against 16.4% for holding; the worst drop was −19% against −42%. A protection, not an edge (alpha t = −1.2).
- **Stocks, earnings (D):** after a round-trip cost every group had negative mean excess, including the baseline of all events (−0.4% over 5 days),
  so the negatives are mostly costs and a slight lag behind the equal-weight benchmark. No group beat the baseline in a way that mattered.
- **Coins:** the ridge model, low volatility and the trend rule look good on large coins (alpha 20 to 28% a year) but with t between 1.4 and 1.6.
  The trend rule cut the worst drop from −83% to −51%. 90-day momentum and 5-day reversal lose (reversal: −85% alpha, t = −4.8).
  The small-coin tier is too short to judge.

Tables follow. Columns: `picks`/`bench` are annual returns of the picks (after costs) and the benchmark; `beta` is how much the picks move with
the benchmark; `alpha` is the yearly return left after removing beta, with its t-statistic; `IC` is the rank correlation of score and later return
(t-statistic next to it); `turnover` is the share of picks replaced each rebalance. For D, `excess %` is the mean return over the benchmark per event after costs, `t` uses one value
per quarter, `beat bench %` is the share of events that beat the benchmark. D's "short" rows show the negated excess.

