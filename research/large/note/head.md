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

