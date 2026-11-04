# 1. Remove the news sentiment score

- **Status:** accepted, November 2026 (#54)

## Context

`src/analysis/sentiment_analysis.py` (about 470 lines) scored each stock from
news headlines (TextBlob polarity), the VIX and sector ETFs. Its ranking weight
was 0 by default, and `get_sentiment_score` returned nothing when the weight
was 0, so it never ran. Experiments could not turn it on, crypto and demo mode
switched it off, and backtests left it out, because there is no point-in-time
news archive.

So it could not be evaluated honestly (out of sample, after costs). The rules
in `AGENTS.md` need that before anything affects the ranking. It still cost
upkeep: a dependency (`textblob`), news fetching in both collectors, a config
flag per universe, an API field, a UI row and fixtures.

## Decision

Remove the sentiment score, its config flag (`use_sentiment`), the
`--no-sentiment` option of the daily script, news fetching
(`get_stock_news`, `normalize_news_item`), the `sentiment_score` API field
and the `textblob` dependency.

The market mood shown in summaries ("Bullish" … "Bearish", from the benchmark's
last daily move) is unrelated and stays.

## Consequences

- About 600 fewer lines, one fewer dependency, and no news requests per stock.
- A `use_sentiment` or `weights.sentiment_score` entry in a user's config is now
  ignored.
- Bringing sentiment back would need a point-in-time news source, so it could
  be backtested and pass the signal and no-signal tests like any other feature.
