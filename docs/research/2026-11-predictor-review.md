# Predictor review on real data (November 2026)

**Question:** why is the predictor bad, and what could give accurate buy and
sell alerts? **Method:** real daily prices from Yahoo Finance, 2016-11 to
2026-11, for the app's 107 stocks and 21 coins; scripts in `research/`.
Nothing in the app was changed.

## Findings

1. **The model has no measurable skill on stocks.** Walk-forward over 7.6
   years, its style of picks made about 24% a year against 18% for the
   universe, with a market beta of 1.45. Alpha is 0.9% a year (t = 0.12).
   Buying the most volatile stocks did as well. The picks were names such as
   CAT, MU, INTC, LRCX, TSLA and AMD.
2. **The inputs do not predict at the 5-day horizon.** None of the ten
   features has |t| ≥ 2 on real stocks. The largest effects are "high beta and
   high volatility did better", which is market risk.
3. **The model is always fully invested.** It ranks assets against each other
   and never says "stay out". Over the last 12 months the coin universe fell
   43% and the picks fell 36%.
4. **Coin ranking has no edge either.** Over 8 years the top picks trailed
   holding all coins; alpha is about zero.
5. **Demo mode flatters the model.** The synthetic market plants a reversal;
   on real stocks 5-day reversal is about zero, and on coins it loses heavily.
6. **Bug:** `AAVE-USD` fails in data preparation (volume dtype) and is dropped.

## Signal families tested

| Family | Stocks (107) | Coins (21) |
|---|---|---|
| Current model (ridge on ten price features) | alpha t = 0.1 | alpha t = 0.1 |
| Hold 21 days, or 20 picks | no skill (t < 0.3) | no skill |
| Momentum only, low volatility only | not significant | not significant |
| Trend rule: above 2 of the 50/100/200-day averages | return 8% vs 18% a year: harmful | return 52% vs 52% a year, worst drop −72% vs −89%: protection, not prediction |
| Earnings surprise and price reaction (about 4,000 events) | beat the market 44–53% of the time over 21 days | not applicable |

The trend rule on Bitcoin alone since 2015 matched buy and hold on return (62%
vs 63% a year) with a worst drop of −67% against −83%. Across window lengths
from 20 to 250 days it beat buy and hold on Sharpe ratio in 23 of 24 cases,
with about 8 to 14 trades a year. It is still not safe.

## Limits

- The stock list is today's large companies (survivorship), which flatters
  every result. The coin list has the same problem.
- The ten years were mostly a rising market.
- Several variants were tried, so a result near t = 2 could be luck.
- Costs assumed: 5 bp per trade for stocks, 15 bp for coins.

## Decisions

- No buy or sell alerts on the 107 large stocks: nothing passed.
- A trend rule may send "move to cash" and "re-enter" alerts for coins,
  labelled as protection.
- Do not re-test these four families on this universe.

## Plan

1. **Large-universe test** (first): about 1,500 US companies and about 100
   coins that were large at some point, the same four families, realistic
   costs that rise for smaller assets, a minimum trading volume, and the last
   two years held back and tested once. Output: one table per universe of
   what passes after costs.
2. **Alert engine with an accuracy bar:** each rule is tested on history
   before it may send alerts; every alert states what to do and how often
   that was right. Show alpha and beta in backtests. Fix the `AAVE-USD` bug.
3. **Coin protection alerts** from the trend rule.
4. **Phone delivery** through one outside channel (Telegram by default), via
   `NotificationChannel` in `api/notifications.py`.
5. **Stock alerts** only for rules that pass step 1.
