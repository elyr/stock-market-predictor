# Large-universe test of the four signal families (November 2026)

**Question:** do the four signal families that failed on the app's 107 stocks and 21 coins
(`2026-11-predictor-review.md`) work on a much larger set of assets, after realistic costs?
**Answer in one line:** see the verdict at the end. Research only: nothing in the app changed.
Scripts and re-run steps: `research/large/`.

## Design (fixed before any result was looked at)

- **Stocks:** today's S&P 500, S&P 400 and S&P 600 members from Wikipedia: 1,502 symbols, of which
  1,483 had Yahoo Finance data (19 had none: ACA, ADIG, BLFS, CWEN-A, FDXF, HLX, HONA, INDV, LEG, LXP,
  MBGL, MFP, QRVO, RAMP, ROKU, TCBI, VGNT, VSNT, VYLR). Ten years of daily adjusted close and volume,
  2016-11 to 2026-11.
- **Coins:** a fixed list of 112 coins that were in the top 100 by market value at some year-end from
  2017 to 2024 (including ones that later collapsed), as far back as Yahoo has them (some from 2014).
  109 had data; **no data:** FTM, GALA, UST. Where the plain `<SYMBOL>-USD` page was empty, Yahoo's own
  ticker was used (for example `UNI7083-USD`). Yahoo's `LUNA20314-USD` is Terra 2.0, not the coin that
  collapsed in 2022; the collapsed one is in the list as `LUNC-USD`. FTT, LUNC and other busted coins are included.
- **Survivorship (read this):** today's index lists leave out every company that was delisted, bought
  or went bankrupt in ten years, and Yahoo's coin coverage leaves out most dead coins. Both flatter
  every result below. A signal that fails here fails for certain; one that passes might still be survivorship.
- **Tradable on date t** if the median dollar volume of the previous 60 days is at least $5M and the price
  at least $2 (stocks), or at least $10M (coins). Yahoo reports coin volume in dollars; stock volume is shares × price.
- **Size tier** by that median dollar volume: large (at least $100M), mid ($20M to $100M), small (below $20M).
- **One-way cost per trade:** stocks 5 / 15 / 40 bp and coins 15 / 40 / 100 bp for large / mid / small, charged on every change of weights.
- **Timing:** data up to the close of day t, traded at the close of day t+1.
- **Benchmark:** equal weight of all tradable assets of the same universe (and tier, in tier tables), without costs. Picks are shown after costs, so the comparison is conservative.
- **Periods:** development = start to 2024-11-10; holdout = 2024-11-11 to 2026-11-11. Development trades must also *end* inside development.
- **Not modelled:** shorting costs and borrow (short-side rows in family D are the negated excess), taxes, delistings inside a holding period (an asset with no later price is skipped).

### The four families

- **A. Ridge on the ten cross-sectional features** (`raw_features`, `gaussian_rank` from `src/models/cross_section.py`; coins have 11 because they use 30- and 90-day momentum). Features ranked among tradable assets only. Expanding-window ridge refitted every 63 days on rows whose labels were already known (`research/variants.py` logic). Top decile, equal weight, hold 5 and 21 days.
- **B. Single inputs, top decile:** 12-1 month momentum (stocks) or 90-day momentum (coins) held 21 days; low volatility held 21 days; 5-day reversal held 5 days.
- **C. Trend rule per asset:** in when the price is above at least 2 of its 50, 100 and 200-day averages, otherwise cash (`research/rule23.py`). Equal weight across tradable assets.
- **D. Earnings (stocks):** terciles of the EPS surprise and of the reaction-day move, set from earlier events only; excess return over 5, 21 and 60 days after the close following the reaction day, minus a round-trip cost; one observation per quarter for the t-statistic (`research/pead.py`).

### The bar, and how many tests

- **Passing in development:** after-cost **alpha** (A, B; against the benchmark, per year) or after-cost **excess** (D; mean excess return per event) that is **positive with t ≥ 3**. For C the alpha of the rule against holding all assets, on monthly returns. Alpha is the part of the return not explained by moving with the benchmark (beta).
- **Confirmed:** passed in development, and in the holdout has the same sign with t ≥ 1.5.
- **Tests counted:** every row of the tables below. By chance alone, about 0.1% of tests reach t ≥ 3 (positive), so with about 150 tests one lucky pass is possible and not a finding.
- "0.5 is a coin flip" applies to IC as well: IC is the average rank correlation between score and later return; 0 means no skill.
- *Research tool, not financial advice.*

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


### Stocks, development

#### A and B

**all**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 281 | 1.42 | 15.77 | 1.00 | -12.58 | -2.55 | -0.01 | -0.46 | 0.68 |
| A ridge, top decile, hold 21d | 67 | 14.07 | 16.51 | 0.90 | -0.01 | -0.00 | -0.01 | -0.37 | 0.82 |
| B 12-1 month momentum, hold 21d | 67 | 24.12 | 16.43 | 0.76 | 10.92 | 1.65 | 0.01 | 0.37 | 0.30 |
| B low volatility, hold 21d | 67 | 7.52 | 16.51 | 0.46 | 0.10 | 0.02 | -0.01 | -0.34 | 0.29 |
| B 5-day reversal, hold 5d | 281 | 2.01 | 15.77 | 1.21 | -14.57 | -3.28 | 0.00 | 0.18 | 0.89 |

**large**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 281 | 10.52 | 15.41 | 1.02 | -3.68 | -0.63 | -0.01 | -0.56 | 0.68 |
| A ridge, top decile, hold 21d | 67 | 4.34 | 16.16 | 0.95 | -9.12 | -1.44 | -0.03 | -1.01 | 0.81 |
| B 12-1 month momentum, hold 21d | 67 | 30.49 | 16.27 | 0.84 | 15.54 | 1.96 | 0.02 | 0.49 | 0.30 |
| B low volatility, hold 21d | 67 | 11.36 | 16.16 | 0.42 | 4.54 | 1.11 | -0.00 | -0.10 | 0.32 |
| B 5-day reversal, hold 5d | 281 | 11.72 | 15.41 | 1.16 | -4.61 | -0.99 | -0.00 | -0.17 | 0.90 |

**mid**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 281 | 4.38 | 13.82 | 0.96 | -7.56 | -1.40 | -0.00 | -0.04 | 0.68 |
| A ridge, top decile, hold 21d | 67 | 14.36 | 14.85 | 0.87 | 1.92 | 0.36 | -0.01 | -0.43 | 0.83 |
| B 12-1 month momentum, hold 21d | 67 | 20.06 | 14.69 | 0.71 | 9.29 | 1.38 | 0.01 | 0.47 | 0.35 |
| B low volatility, hold 21d | 67 | 6.23 | 14.85 | 0.52 | -1.40 | -0.35 | -0.01 | -0.27 | 0.35 |
| B 5-day reversal, hold 5d | 281 | 6.50 | 13.82 | 1.20 | -7.99 | -1.73 | 0.01 | 0.69 | 0.90 |

**small**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 281 | -9.34 | 18.79 | 1.04 | -27.02 | -5.53 | -0.01 | -0.85 | 0.69 |
| A ridge, top decile, hold 21d | 67 | 12.99 | 19.37 | 0.94 | -3.82 | -0.72 | 0.01 | 0.47 | 0.83 |
| B 12-1 month momentum, hold 21d | 67 | 20.62 | 19.25 | 0.85 | 4.56 | 0.74 | 0.00 | 0.10 | 0.38 |
| B low volatility, hold 21d | 67 | 3.06 | 19.37 | 0.53 | -6.69 | -1.82 | -0.03 | -1.13 | 0.35 |
| B 5-day reversal, hold 5d | 281 | -13.28 | 18.79 | 1.18 | -33.24 | -6.11 | -0.00 | -0.58 | 0.89 |

#### C

**all**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 1809 | 3.89 | 16.43 | 0.43 | 0.78 | -18.92 | -41.97 | 0.40 | -2.63 | -1.21 | -6.26 | -1.74 |

**large**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 1809 | 6.35 | 15.83 | 0.69 | 0.80 | -16.00 | -39.05 | 0.42 | -0.38 | -0.19 | -5.32 | -1.06 |

**mid**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 1809 | 3.50 | 14.69 | 0.38 | 0.70 | -21.06 | -44.43 | 0.38 | -2.18 | -0.97 | -4.27 | -1.10 |

**small**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 1809 | 1.58 | 19.57 | 0.19 | 0.84 | -23.00 | -42.82 | 0.42 | -6.33 | -2.46 | -9.48 | -2.68 |

#### D

**all**

| signal | horizon | events | excess % | t | beat bench % |
|---|---|---|---|---|---|
| D All events (baseline) | 5 | 37310 | -0.43 | -8.96 | 44.29 |
| D Surprise top third (long) | 5 | 13437 | -0.45 | -6.96 | 43.85 |
| D Surprise bottom third (short) | 5 | 12100 | -0.38 | -5.41 | 45.60 |
| D Reaction top third (long) | 5 | 12832 | -0.38 | -7.17 | 45.22 |
| D Reaction bottom third (short) | 5 | 12676 | -0.33 | -4.44 | 47.27 |
| D Surprise and reaction both top (long) | 5 | 6283 | -0.41 | -4.46 | 45.11 |
| D Surprise and reaction both bottom (short) | 5 | 5934 | -0.42 | -4.90 | 45.87 |
| D All events (baseline) | 21 | 36569 | -0.52 | -4.88 | 45.35 |
| D Surprise top third (long) | 21 | 13257 | -0.45 | -3.15 | 45.42 |
| D Surprise bottom third (short) | 21 | 11796 | -0.22 | -2.11 | 50.49 |
| D Reaction top third (long) | 21 | 12559 | -0.38 | -2.88 | 46.35 |
| D Reaction bottom third (short) | 21 | 12421 | -0.22 | -0.73 | 51.09 |
| D Surprise and reaction both top (long) | 21 | 6181 | -0.38 | -2.55 | 46.08 |
| D Surprise and reaction both bottom (short) | 21 | 5787 | -0.27 | -1.80 | 50.42 |
| D All events (baseline) | 60 | 36417 | -0.66 | -4.39 | 45.61 |
| D Surprise top third (long) | 60 | 13226 | -0.24 | -0.90 | 45.82 |
| D Surprise bottom third (short) | 60 | 11746 | 0.08 | -0.29 | 52.37 |
| D Reaction top third (long) | 60 | 12500 | -0.55 | -2.64 | 45.87 |
| D Reaction bottom third (short) | 60 | 12357 | -0.24 | -1.27 | 52.03 |
| D Surprise and reaction both top (long) | 60 | 6166 | -0.27 | -0.92 | 46.58 |
| D Surprise and reaction both bottom (short) | 60 | 5760 | -0.10 | -0.80 | 51.98 |

**large**

| signal | horizon | events | excess % | t | beat bench % |
|---|---|---|---|---|---|
| D All events (baseline) | 5 | 11528 | -0.11 | -2.25 | 47.81 |
| D Surprise top third (long) | 5 | 3258 | -0.14 | -1.90 | 47.58 |
| D Surprise bottom third (short) | 5 | 3562 | -0.08 | -0.59 | 48.85 |
| D Reaction top third (long) | 5 | 3831 | -0.09 | -0.88 | 48.53 |
| D Reaction bottom third (short) | 5 | 3948 | -0.10 | -0.96 | 49.77 |
| D Surprise and reaction both top (long) | 5 | 1411 | -0.11 | -1.04 | 48.33 |
| D Surprise and reaction both bottom (short) | 5 | 1698 | -0.06 | 0.20 | 49.35 |
| D All events (baseline) | 21 | 11245 | -0.12 | -1.22 | 47.79 |
| D Surprise top third (long) | 21 | 3201 | 0.03 | -1.00 | 47.11 |
| D Surprise bottom third (short) | 21 | 3453 | -0.01 | -0.27 | 50.59 |
| D Reaction top third (long) | 21 | 3730 | 0.05 | 0.30 | 48.66 |
| D Reaction bottom third (short) | 21 | 3847 | 0.02 | 0.45 | 51.99 |
| D Surprise and reaction both top (long) | 21 | 1381 | 0.10 | -0.78 | 48.15 |
| D Surprise and reaction both bottom (short) | 21 | 1648 | 0.19 | 0.84 | 51.09 |
| D All events (baseline) | 60 | 11167 | -0.36 | -1.30 | 47.55 |
| D Surprise top third (long) | 60 | 3186 | 0.06 | 0.04 | 47.49 |
| D Surprise bottom third (short) | 60 | 3429 | 0.53 | 0.91 | 52.87 |
| D Reaction top third (long) | 60 | 3700 | -0.09 | -0.16 | 48.19 |
| D Reaction bottom third (short) | 60 | 3816 | 0.18 | -0.31 | 52.02 |
| D Surprise and reaction both top (long) | 60 | 1376 | 0.05 | -0.40 | 48.26 |
| D Surprise and reaction both bottom (short) | 60 | 1636 | 0.77 | 0.97 | 52.44 |

**mid**

| signal | horizon | events | excess % | t | beat bench % |
|---|---|---|---|---|---|
| D All events (baseline) | 5 | 15253 | -0.33 | -6.39 | 45.87 |
| D Surprise top third (long) | 5 | 5739 | -0.26 | -3.13 | 46.07 |
| D Surprise bottom third (short) | 5 | 4922 | -0.34 | -3.75 | 46.14 |
| D Reaction top third (long) | 5 | 5235 | -0.19 | -2.48 | 47.83 |
| D Reaction bottom third (short) | 5 | 5323 | -0.21 | -2.11 | 48.49 |
| D Surprise and reaction both top (long) | 5 | 2641 | -0.15 | -1.41 | 48.35 |
| D Surprise and reaction both bottom (short) | 5 | 2442 | -0.31 | -2.74 | 46.97 |
| D All events (baseline) | 21 | 14959 | -0.35 | -1.65 | 46.62 |
| D Surprise top third (long) | 21 | 5659 | -0.15 | -1.57 | 47.61 |
| D Surprise bottom third (short) | 21 | 4801 | -0.19 | -1.44 | 50.89 |
| D Reaction top third (long) | 21 | 5114 | -0.05 | -0.01 | 49.02 |
| D Reaction bottom third (short) | 21 | 5225 | -0.20 | -0.52 | 51.50 |
| D Surprise and reaction both top (long) | 21 | 2594 | 0.09 | 0.55 | 49.00 |
| D Surprise and reaction both bottom (short) | 21 | 2381 | -0.26 | -0.84 | 51.57 |
| D All events (baseline) | 60 | 14908 | -0.33 | -2.08 | 46.79 |
| D Surprise top third (long) | 60 | 5648 | 0.21 | -0.28 | 47.01 |
| D Surprise bottom third (short) | 60 | 4786 | -0.20 | -0.61 | 51.38 |
| D Reaction top third (long) | 60 | 5094 | -0.04 | -0.11 | 47.68 |
| D Reaction bottom third (short) | 60 | 5203 | -0.44 | -0.54 | 51.68 |
| D Surprise and reaction both top (long) | 60 | 2589 | 0.30 | 0.86 | 49.05 |
| D Surprise and reaction both bottom (short) | 60 | 2373 | -0.26 | -0.47 | 50.78 |

**small**

| signal | horizon | events | excess % | t | beat bench % |
|---|---|---|---|---|---|
| D All events (baseline) | 5 | 10529 | -0.90 | -11.50 | 38.34 |
| D Surprise top third (long) | 5 | 4440 | -0.93 | -9.67 | 37.77 |
| D Surprise bottom third (short) | 5 | 3616 | -0.74 | -6.06 | 42.28 |
| D Reaction top third (long) | 5 | 3766 | -0.93 | -9.02 | 38.21 |
| D Reaction bottom third (short) | 5 | 3405 | -0.84 | -7.52 | 42.61 |
| D Surprise and reaction both top (long) | 5 | 2231 | -0.92 | -7.82 | 37.97 |
| D Surprise and reaction both bottom (short) | 5 | 1794 | -0.89 | -6.61 | 42.20 |
| D All events (baseline) | 21 | 10365 | -1.11 | -6.58 | 41.65 |
| D Surprise top third (long) | 21 | 4397 | -1.19 | -6.21 | 41.41 |
| D Surprise bottom third (short) | 21 | 3542 | -0.58 | -2.94 | 48.59 |
| D Reaction top third (long) | 21 | 3715 | -1.17 | -5.47 | 41.88 |
| D Reaction bottom third (short) | 21 | 3349 | -0.70 | -3.30 | 48.34 |
| D Surprise and reaction both top (long) | 21 | 2206 | -1.23 | -5.55 | 41.61 |
| D Surprise and reaction both bottom (short) | 21 | 1758 | -0.83 | -3.49 | 47.72 |
| D All events (baseline) | 60 | 10342 | -1.40 | -5.67 | 41.96 |
| D Surprise top third (long) | 60 | 4392 | -1.17 | -2.73 | 42.46 |
| D Surprise bottom third (short) | 60 | 3531 | -0.04 | -0.59 | 52.87 |
| D Reaction top third (long) | 60 | 3706 | -1.69 | -6.49 | 41.50 |
| D Reaction bottom third (short) | 60 | 3338 | -0.60 | -1.76 | 51.74 |
| D Surprise and reaction both top (long) | 60 | 2201 | -1.34 | -3.15 | 41.75 |
| D Surprise and reaction both bottom (short) | 60 | 1751 | -0.75 | -2.07 | 52.20 |


### Coins, development

#### A and B

**all**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 476 | 27.16 | 9.66 | 0.66 | 14.21 | 1.18 | 0.07 | 6.29 | 0.31 |
| A ridge, top decile, hold 21d | 112 | 21.90 | 12.95 | 0.63 | 6.46 | 0.58 | 0.09 | 4.06 | 0.36 |
| B 90-day momentum, hold 21d | 116 | -7.64 | 8.85 | 0.83 | -9.05 | -0.47 | -0.01 | -0.33 | 0.44 |
| B low volatility, hold 21d | 119 | 29.36 | 8.22 | 0.64 | 14.96 | 1.10 | 0.10 | 4.68 | 0.26 |
| B 5-day reversal, hold 5d | 503 | -58.94 | 5.91 | 1.02 | -84.63 | -4.82 | 0.01 | 1.22 | 0.89 |

**large**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 346 | 39.81 | 17.30 | 0.57 | 19.90 | 1.46 | 0.08 | 4.82 | 0.30 |
| A ridge, top decile, hold 21d | 80 | 51.01 | 15.04 | 0.65 | 28.42 | 1.55 | 0.11 | 3.31 | 0.44 |
| B 90-day momentum, hold 21d | 79 | -24.70 | 16.49 | 0.88 | -28.75 | -1.12 | -0.03 | -0.93 | 0.46 |
| B low volatility, hold 21d | 80 | 53.48 | 15.04 | 0.64 | 28.14 | 1.61 | 0.12 | 3.47 | 0.27 |
| B 5-day reversal, hold 5d | 346 | -41.94 | 17.30 | 0.99 | -61.19 | -3.36 | 0.02 | 1.55 | 0.91 |

**mid**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 266 | 44.98 | 59.71 | 0.79 | 7.22 | 0.23 | 0.07 | 4.56 | 0.40 |
| A ridge, top decile, hold 21d | 62 | 22.60 | 35.21 | 0.80 | -2.10 | -0.09 | 0.10 | 3.33 | 0.46 |
| B 90-day momentum, hold 21d | 60 | 2.44 | 30.46 | 0.76 | -12.77 | -0.48 | -0.04 | -1.20 | 0.59 |
| B low volatility, hold 21d | 62 | 64.51 | 35.36 | 1.05 | 29.63 | 0.78 | 0.09 | 2.91 | 0.42 |
| B 5-day reversal, hold 5d | 266 | -33.05 | 59.81 | 0.95 | -73.67 | -2.94 | 0.04 | 3.11 | 0.91 |

**small**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 26 | 15.87 | 248.05 | 0.56 | -61.50 | -1.63 | -0.01 | -0.16 | 0.67 |
| B 5-day reversal, hold 5d | 23 | 52.69 | 608.32 | 0.98 | -146.27 | -2.12 | 0.10 | 1.64 | 0.86 |

#### C

**all**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 2358 | 43.18 | 17.11 | 1.02 | 0.61 | -51.09 | -83.18 | 0.58 | 20.31 | 1.58 | 48.82 | 2.67 |

**large**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 1689 | 23.95 | 18.07 | 0.68 | 0.63 | -62.84 | -84.80 | 0.60 | 4.47 | 0.38 | 30.00 | 0.59 |

**mid**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 1251 | 12.69 | -3.94 | 0.51 | 0.34 | -50.01 | -84.50 | 0.40 | 8.12 | 0.60 | 87.04 | -0.14 |

## Holdout results (2024-11-11 to 2026-11-11), run once

The holdout was run once, after the development results above were committed and pushed. No rule was changed afterwards and no bug was found,
so there was no re-run. The same 128 tests were run again. Because **no signal passed in development, none can be confirmed**; the holdout
is shown for completeness. About two years is short: 5-day signals have about 100 periods, 21-day signals about 25, earnings about 8 quarters.
No holdout test reached t ≥ 3 with a positive effect.

Holdout rows that look interesting but do not count (they did not pass in development):

- **Coins, low volatility, hold 21 days:** alpha 40% a year, t = 2.2 (large coins 28%, t = 1.5; mid 35%, t = 1.4). In development: 15%, t = 1.1.
- **Stocks, selling the bottom third of EPS surprises, 60 days:** excess +0.9% per event, t = 2.3 (large stocks +1.6%, t = 2.8), but shorting costs are not modelled. In development: +0.1%, t = −0.3.

Clear failures that repeat in the holdout: 5-day reversal (stocks −10% alpha, t = −1.9; coins −87%, t = −4.2), the stock trend rule (alpha t = −2.5),
the ridge model on small stocks and small coins, and the "reaction top third" earnings group (negative after costs at every horizon). Long surprise groups at 21 and 60 days were slightly positive but not significant (t ≤ 2.0).



### Stocks, holdout

#### A and B

**all**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 100 | 8.37 | 12.88 | 1.05 | -2.95 | -0.22 | 0.00 | 0.27 | 0.46 |
| A ridge, top decile, hold 21d | 22 | 13.55 | 10.70 | 1.50 | -0.19 | -0.02 | 0.01 | 0.29 | 0.62 |
| B 12-1 month momentum, hold 21d | 22 | 24.17 | 10.37 | 1.16 | 12.07 | 0.90 | 0.02 | 0.64 | 0.29 |
| B low volatility, hold 21d | 22 | 1.02 | 10.70 | 0.36 | -2.62 | -0.38 | -0.04 | -0.82 | 0.28 |
| B 5-day reversal, hold 5d | 100 | 2.23 | 12.88 | 1.06 | -10.34 | -1.92 | 0.00 | 0.23 | 0.90 |

**large**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 100 | 16.61 | 13.77 | 1.27 | 2.34 | 0.13 | 0.01 | 0.30 | 0.44 |
| A ridge, top decile, hold 21d | 22 | 15.33 | 11.63 | 1.78 | -2.09 | -0.15 | 0.02 | 0.34 | 0.61 |
| B 12-1 month momentum, hold 21d | 22 | 31.41 | 11.27 | 1.56 | 14.41 | 0.83 | 0.03 | 0.66 | 0.28 |
| B low volatility, hold 21d | 22 | 1.88 | 11.63 | 0.27 | -0.83 | -0.11 | -0.03 | -0.62 | 0.31 |
| B 5-day reversal, hold 5d | 100 | 12.31 | 13.77 | 1.04 | -1.35 | -0.20 | 0.00 | 0.27 | 0.90 |

**mid**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 100 | 4.80 | 11.98 | 1.00 | -5.65 | -0.55 | 0.01 | 0.34 | 0.48 |
| A ridge, top decile, hold 21d | 22 | 13.45 | 9.05 | 1.42 | 1.94 | 0.22 | 0.01 | 0.22 | 0.66 |
| B 12-1 month momentum, hold 21d | 22 | 21.11 | 8.69 | 0.97 | 12.24 | 1.06 | 0.02 | 0.62 | 0.33 |
| B low volatility, hold 21d | 22 | -0.75 | 9.05 | 0.44 | -4.56 | -0.65 | -0.04 | -0.93 | 0.31 |
| B 5-day reversal, hold 5d | 100 | 0.04 | 11.98 | 1.08 | -11.75 | -2.09 | 0.00 | 0.12 | 0.90 |

**small**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 100 | -1.60 | 14.01 | 1.07 | -15.09 | -2.17 | 0.01 | 0.54 | 0.53 |
| A ridge, top decile, hold 21d | 22 | 22.61 | 13.47 | 1.25 | 6.34 | 0.54 | 0.04 | 0.85 | 0.71 |
| B 12-1 month momentum, hold 21d | 22 | 23.60 | 13.24 | 1.03 | 8.87 | 1.35 | 0.02 | 0.57 | 0.41 |
| B low volatility, hold 21d | 22 | 0.22 | 13.47 | 0.52 | -6.59 | -1.10 | -0.06 | -1.55 | 0.31 |
| B 5-day reversal, hold 5d | 100 | -17.25 | 14.01 | 1.03 | -31.80 | -4.21 | 0.01 | 0.45 | 0.89 |

#### C

**all**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 502 | 1.41 | 13.04 | 0.21 | 0.78 | -11.48 | -22.65 | 0.55 | -5.33 | -2.52 | -7.01 | -1.14 |

**large**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 502 | 4.01 | 14.15 | 0.53 | 0.86 | -9.37 | -19.51 | 0.58 | -3.77 | -1.65 | -4.96 | -0.82 |

**mid**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 502 | 0.72 | 11.80 | 0.13 | 0.69 | -12.33 | -24.47 | 0.54 | -5.35 | -2.38 | -6.59 | -1.02 |

**small**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 502 | -2.16 | 14.16 | -0.17 | 0.77 | -15.03 | -24.75 | 0.52 | -8.93 | -3.58 | -9.03 | -1.54 |

#### D

**all**

| signal | horizon | events | excess % | t | beat bench % |
|---|---|---|---|---|---|
| D All events (baseline) | 5 | 11048 | -0.28 | -2.50 | 46.58 |
| D Surprise top third (long) | 5 | 3417 | -0.13 | -0.84 | 48.87 |
| D Surprise bottom third (short) | 5 | 3628 | -0.33 | -1.87 | 48.40 |
| D Reaction top third (long) | 5 | 3874 | -0.42 | -4.38 | 45.95 |
| D Reaction bottom third (short) | 5 | 4049 | -0.39 | -2.01 | 47.25 |
| D Surprise and reaction both top (long) | 5 | 1617 | -0.36 | -1.38 | 47.43 |
| D Surprise and reaction both bottom (short) | 5 | 1832 | -0.47 | -1.89 | 47.71 |
| D All events (baseline) | 21 | 10232 | -0.27 | 0.57 | 44.55 |
| D Surprise top third (long) | 21 | 3188 | 0.39 | 1.95 | 48.71 |
| D Surprise bottom third (short) | 21 | 3353 | -0.27 | -1.15 | 54.10 |
| D Reaction top third (long) | 21 | 3623 | -0.53 | -0.91 | 44.44 |
| D Reaction bottom third (short) | 21 | 3782 | -0.73 | -1.71 | 51.93 |
| D Surprise and reaction both top (long) | 21 | 1534 | 0.13 | 0.04 | 47.72 |
| D Surprise and reaction both bottom (short) | 21 | 1715 | -0.61 | -1.72 | 53.99 |
| D All events (baseline) | 60 | 10094 | -0.64 | -2.62 | 43.09 |
| D Surprise top third (long) | 60 | 3136 | 0.77 | 0.63 | 46.75 |
| D Surprise bottom third (short) | 60 | 3320 | 0.90 | 2.33 | 56.72 |
| D Reaction top third (long) | 60 | 3572 | -0.95 | -3.51 | 43.45 |
| D Reaction bottom third (short) | 60 | 3727 | -0.67 | -0.51 | 54.76 |
| D Surprise and reaction both top (long) | 60 | 1509 | 0.13 | 0.10 | 46.72 |
| D Surprise and reaction both bottom (short) | 60 | 1696 | 0.19 | 0.92 | 55.66 |

**large**

| signal | horizon | events | excess % | t | beat bench % |
|---|---|---|---|---|---|
| D All events (baseline) | 5 | 4833 | -0.01 | 0.33 | 49.35 |
| D Surprise top third (long) | 5 | 1115 | 0.26 | 1.37 | 52.38 |
| D Surprise bottom third (short) | 5 | 1565 | -0.29 | -1.49 | 49.27 |
| D Reaction top third (long) | 5 | 1672 | -0.29 | -1.69 | 47.97 |
| D Reaction bottom third (short) | 5 | 1788 | -0.40 | -2.07 | 49.16 |
| D Surprise and reaction both top (long) | 5 | 499 | -0.10 | -0.09 | 50.10 |
| D Surprise and reaction both bottom (short) | 5 | 760 | -0.44 | -1.89 | 51.05 |
| D All events (baseline) | 21 | 4429 | -0.04 | 1.04 | 45.61 |
| D Surprise top third (long) | 21 | 1008 | 0.88 | 1.29 | 51.69 |
| D Surprise bottom third (short) | 21 | 1446 | 0.24 | -0.89 | 57.05 |
| D Reaction top third (long) | 21 | 1538 | -0.47 | 0.64 | 45.06 |
| D Reaction bottom third (short) | 21 | 1663 | -0.60 | -1.56 | 52.98 |
| D Surprise and reaction both top (long) | 21 | 459 | 0.48 | 1.13 | 50.76 |
| D Surprise and reaction both bottom (short) | 21 | 714 | -0.20 | -0.91 | 56.44 |
| D All events (baseline) | 60 | 4346 | -0.46 | -1.44 | 43.67 |
| D Surprise top third (long) | 60 | 980 | 1.61 | 0.38 | 49.18 |
| D Surprise bottom third (short) | 60 | 1430 | 1.63 | 2.77 | 58.60 |
| D Reaction top third (long) | 60 | 1503 | -1.15 | -2.14 | 42.51 |
| D Reaction bottom third (short) | 60 | 1627 | -0.03 | 0.52 | 56.36 |
| D Surprise and reaction both top (long) | 60 | 444 | 0.25 | -0.15 | 47.30 |
| D Surprise and reaction both bottom (short) | 60 | 704 | 0.90 | 1.56 | 58.10 |

**mid**

| signal | horizon | events | excess % | t | beat bench % |
|---|---|---|---|---|---|
| D All events (baseline) | 5 | 4481 | -0.37 | -2.72 | 45.68 |
| D Surprise top third (long) | 5 | 1558 | -0.11 | -0.20 | 49.10 |
| D Surprise bottom third (short) | 5 | 1467 | -0.23 | -1.43 | 49.35 |
| D Reaction top third (long) | 5 | 1557 | -0.33 | -1.39 | 45.60 |
| D Reaction bottom third (short) | 5 | 1657 | -0.19 | -1.22 | 48.34 |
| D Surprise and reaction both top (long) | 5 | 729 | -0.21 | 0.16 | 48.29 |
| D Surprise and reaction both bottom (short) | 5 | 748 | -0.19 | -0.84 | 49.20 |
| D All events (baseline) | 21 | 4165 | -0.36 | -1.34 | 43.43 |
| D Surprise top third (long) | 21 | 1470 | 0.37 | -0.58 | 48.03 |
| D Surprise bottom third (short) | 21 | 1346 | -0.56 | -0.93 | 53.49 |
| D Reaction top third (long) | 21 | 1468 | -0.57 | -1.35 | 43.73 |
| D Reaction bottom third (short) | 21 | 1549 | -0.67 | -2.01 | 53.13 |
| D Surprise and reaction both top (long) | 21 | 700 | 0.23 | -0.74 | 48.14 |
| D Surprise and reaction both bottom (short) | 21 | 696 | -0.64 | -1.82 | 54.89 |
| D All events (baseline) | 60 | 4125 | -0.90 | -2.74 | 42.98 |
| D Surprise top third (long) | 60 | 1453 | 0.40 | 0.44 | 46.18 |
| D Surprise bottom third (short) | 60 | 1335 | 0.68 | 1.58 | 56.03 |
| D Reaction top third (long) | 60 | 1456 | -1.12 | -2.44 | 43.82 |
| D Reaction bottom third (short) | 60 | 1535 | -0.79 | -0.65 | 54.14 |
| D Surprise and reaction both top (long) | 60 | 693 | -0.19 | -0.25 | 46.75 |
| D Surprise and reaction both bottom (short) | 60 | 691 | 0.22 | 0.79 | 55.86 |

**small**

| signal | horizon | events | excess % | t | beat bench % |
|---|---|---|---|---|---|
| D All events (baseline) | 5 | 1734 | -0.75 | -5.00 | 41.41 |
| D Surprise top third (long) | 5 | 744 | -0.69 | -2.40 | 43.15 |
| D Surprise bottom third (short) | 5 | 596 | -0.75 | -1.42 | 45.47 |
| D Reaction top third (long) | 5 | 645 | -0.97 | -3.84 | 39.69 |
| D Reaction bottom third (short) | 5 | 604 | -0.98 | -2.59 | 39.90 |
| D Surprise and reaction both top (long) | 5 | 389 | -0.93 | -2.44 | 40.87 |
| D Surprise and reaction both bottom (short) | 5 | 324 | -1.32 | -2.00 | 38.58 |
| D All events (baseline) | 21 | 1638 | -0.90 | 0.28 | 41.21 |
| D Surprise top third (long) | 21 | 710 | -0.56 | 0.72 | 42.96 |
| D Surprise bottom third (short) | 21 | 561 | -0.66 | -1.02 | 49.02 |
| D Reaction top third (long) | 21 | 617 | -0.93 | 0.27 | 40.68 |
| D Reaction bottom third (short) | 21 | 570 | -1.02 | -1.58 | 46.67 |
| D Surprise and reaction both top (long) | 21 | 375 | -0.70 | 0.52 | 41.33 |
| D Surprise and reaction both bottom (short) | 21 | 305 | -1.23 | -1.17 | 45.25 |
| D All events (baseline) | 60 | 1623 | -0.53 | -0.74 | 42.08 |
| D Surprise top third (long) | 60 | 703 | 0.15 | 1.20 | 43.95 |
| D Surprise bottom third (short) | 60 | 555 | 0.00 | 0.69 | 54.95 |
| D Reaction top third (long) | 60 | 613 | 0.04 | 0.82 | 42.74 |
| D Reaction bottom third (short) | 60 | 565 | -1.82 | -1.62 | 52.57 |
| D Surprise and reaction both top (long) | 60 | 372 | 0.42 | 1.26 | 42.74 |
| D Surprise and reaction both bottom (short) | 60 | 301 | -0.85 | 0.44 | 53.82 |


### Coins, holdout

#### A and B

**all**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 145 | -24.62 | -34.74 | 0.56 | -8.43 | -0.60 | 0.09 | 4.74 | 0.22 |
| A ridge, top decile, hold 21d | 34 | 4.82 | -32.28 | 0.80 | 31.27 | 1.69 | 0.17 | 4.03 | 0.28 |
| B 90-day momentum, hold 21d | 34 | -38.39 | -32.28 | 0.56 | -24.93 | -0.90 | -0.04 | -0.97 | 0.40 |
| B low volatility, hold 21d | 34 | 14.86 | -32.28 | 0.80 | 40.30 | 2.17 | 0.16 | 3.84 | 0.23 |
| B 5-day reversal, hold 5d | 145 | -73.16 | -34.84 | 0.94 | -86.81 | -4.24 | 0.00 | 0.03 | 0.88 |

**large**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 145 | -11.66 | -28.45 | 0.32 | -4.94 | -0.43 | 0.08 | 2.81 | 0.22 |
| A ridge, top decile, hold 21d | 34 | 4.69 | -26.45 | 0.19 | 7.54 | 0.77 | 0.15 | 2.21 | 0.15 |
| B 90-day momentum, hold 21d | 34 | -37.41 | -26.45 | 0.54 | -21.88 | -0.59 | -0.03 | -0.67 | 0.43 |
| B low volatility, hold 21d | 34 | 22.50 | -26.45 | 0.38 | 28.30 | 1.52 | 0.15 | 2.23 | 0.12 |
| B 5-day reversal, hold 5d | 145 | -54.83 | -28.45 | 0.94 | -43.28 | -1.87 | -0.03 | -1.37 | 0.91 |

**mid**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 143 | -22.32 | -35.01 | 0.78 | 9.51 | 0.38 | 0.09 | 4.26 | 0.38 |
| A ridge, top decile, hold 21d | 34 | -3.42 | -33.80 | 1.04 | 39.37 | 1.62 | 0.16 | 3.60 | 0.52 |
| B 90-day momentum, hold 21d | 34 | -43.73 | -33.80 | 0.60 | -21.70 | -0.53 | -0.07 | -1.57 | 0.54 |
| B low volatility, hold 21d | 34 | -10.15 | -33.80 | 1.06 | 34.50 | 1.43 | 0.16 | 3.62 | 0.44 |
| B 5-day reversal, hold 5d | 143 | -67.56 | -35.22 | 0.95 | -63.85 | -2.22 | 0.02 | 1.15 | 0.87 |

**small**

| signal | periods | picks %/yr | bench %/yr | beta | alpha %/yr | alpha t | IC | IC t | turnover |
|---|---|---|---|---|---|---|---|---|---|
| A ridge, top decile, hold 5d | 25 | -78.18 | -34.57 | 0.43 | -134.60 | -3.39 | 0.13 | 2.10 | 0.55 |
| B 5-day reversal, hold 5d | 25 | -92.18 | -34.57 | 0.89 | -199.90 | -2.18 | 0.12 | 2.48 | 0.93 |

#### C

**all**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 731 | -12.48 | -34.38 | -0.17 | -0.25 | -62.26 | -82.52 | 0.60 | 8.64 | 0.50 | -52.68 | -0.90 |

**large**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 731 | -8.11 | -26.00 | -0.04 | -0.10 | -55.35 | -77.12 | 0.56 | 5.57 | 0.38 | -13.22 | -1.04 |

**mid**

| signal | days | rule %/yr | hold %/yr | rule Sharpe | hold Sharpe | rule worst drop % | hold worst drop % | beta | alpha %/yr | alpha t | in-out %/yr | in-out t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C trend rule (2 of 50/100/200) | 708 | -5.34 | -33.83 | 0.06 | -0.19 | -64.13 | -84.76 | 0.61 | 15.65 | 0.81 | -37.39 | -0.58 |



## Verdict

Counting rule: confirmed = positive with t ≥ 3 in development and the same sign with t ≥ 1.5 in the holdout.

### US stocks (about 1,480 companies, large / mid / small)

- **Confirmed:** none.
- **Passed development, failed the holdout:** none (the best development t was 1.96, 12-1 month momentum on large stocks; in the holdout t = 0.8).
- **Everything else:** nothing is usable. The ridge model, 5-day reversal and the trend rule lose money after costs against holding the same stocks
  (the trend rule still cuts the worst drop roughly in half, in both periods, as protection, not as a way to earn more).
  Momentum is positive but weak in both periods (alpha 9 to 15% a year on large and mid stocks, t between 0.8 and 2.0).
  Earnings surprises and reactions do not beat the benchmark after costs. Small stocks are worst because their trading costs are highest.
  A stock-alert engine has nothing to stand on here.

### Coins (109 coins, large / mid / small)

- **Confirmed:** none.
- **Passed development, failed the holdout:** none.
- **Everything else:** low volatility, the ridge model at 21 days and the trend rule have positive alpha in both periods on large and mid coins, but never with t ≥ 3 in
  development; low volatility reached t = 2.2 in the holdout. That is a lead worth testing on more data, not a result.
  The trend rule again cut the worst drop (−83% to −51% in development; −83% to −62% in the holdout, when coins fell 34% a year and the rule lost 12% a year). Reversal and 90-day momentum lose. Small coins are too short and too costly to judge.
  The coin list suffers from survivorship, so even these leads are probably flattered.

### What this means for the plan

Step 5 of the plan (stock alerts) has no rule to build on. Step 3 (coin protection alerts from the trend rule) is supported as *protection*, not as prediction.
Anything new would need a new idea, not a new tuning of these families.

### Limits

Survivorship (above); one decade, mostly rising; holdout only two years; costs are fixed assumptions, not measured; the market-neutral short sides were not
costed; the benchmark is equal-weight and has no costs, which favours the benchmark; the large coin tier has few assets early on.
