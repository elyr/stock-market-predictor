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



_Holdout results and the verdict are added after the holdout run (step 3 of the plan)._
