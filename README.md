# Stock Market Prediction System

Ranks a universe of liquid US stocks by how likely each is to close higher on the next
trading day, combining technical indicators, a machine learning ensemble and market
sentiment into one score. A built-in walk-forward backtest measures whether those
scores would actually have beaten simply holding every stock.

> **Educational and research use only. Not financial advice.** Next-day stock moves
> are close to random. Run the backtest before trusting any score.

## Features

- **Technical analysis:** RSI (Wilder), MACD, Bollinger Bands, Stochastic, CCI, MFI, ATR, OBV, ADX, moving averages, candlestick and chart patterns
- **Machine learning:** Random Forest, XGBoost and a neural network trained on the pooled history of every stock, evaluated on a chronological hold-out (optional LSTM with TensorFlow)
- **Sentiment:** news headline polarity, VIX-based fear/greed, sector ETF momentum
- **Composite ranking:** configurable weights, liquidity and price filters, STRONG BUY / BUY / HOLD / AVOID labels
- **Backtesting:** walk-forward simulation of the daily top-N picks with transaction costs, attribution by score component, and significance statistics
- **Interfaces:** command line, web dashboard, Python API
- **Demo mode:** runs everything on synthetic data with no internet connection

## Quick start

Requires Python 3.10 or newer.

```bash
git clone https://github.com/elyr/stock-market-predictor.git
cd stock-market-predictor

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Try it without network access first:

```bash
python src/cli.py analyze --demo
```

Then on real market data (Yahoo Finance, no API key needed):

```bash
python main.py                                   # top 10 of ten large caps
python src/cli.py analyze                        # full configured universe (~100 stocks)
python src/cli.py backtest --top-n 10            # how would these picks have done?
python run_dashboard.py                          # web UI at http://127.0.0.1:8050
```

## Usage

### Command line

```bash
# Rank stocks
python src/cli.py analyze
python src/cli.py analyze --symbols AAPL,MSFT,GOOGL,AMZN,NVDA --top-n 3
python src/cli.py analyze --output my_picks.csv

# One stock in detail
python src/cli.py single --symbol AAPL

# Index moves and market sentiment
python src/cli.py market

# Backtest the daily picks
python src/cli.py backtest                                  # config universe, last 120 days
python src/cli.py backtest --days 250 --period 3y --cost-bps 10
python src/cli.py backtest --no-ml                          # much faster

# Show configuration
python src/cli.py config
```

Every command except `market` and `config` accepts `--demo` to use synthetic data.

### Reading a backtest

The backtest buys the top N stocks at each day's close, sells at the next close, and
compares the result with an equal-weight portfolio of the whole universe.

| Column | Meaning |
|---|---|
| Excess/day | average daily return above the universe, in basis points |
| t-stat | whether that excess is distinguishable from luck: between −2 and 2 it is not |
| Days > univ. | share of days the picks beat the universe |

Rows for *Technical only*, *Momentum only*, *Volume only* and *ML only* show which part
of the score carries signal. Results are also saved to `data/` as CSV files and an
interactive HTML chart.

### Web dashboard

```bash
python run_dashboard.py
```

Enter symbols (or tick **Demo mode**), then **Analyze Stocks** for the ranked table,
score breakdown and sector mix, or **Backtest These Rules** for the equity curves and
metrics.

### Python API

```python
from src.prediction import StockRanker
from src.backtest import Backtester

ranker = StockRanker()
result = ranker.get_top_10_recommendations(['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'JPM', 'XOM'], top_n=3)
print(result['top_10'][['Symbol', 'Composite_Score', 'Recommendation']])
print(result['analysis_summary']['ml_test_accuracy'])

backtest = Backtester.from_config(ranker, top_n=3, test_days=60).run_symbols(['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'JPM', 'XOM', 'PG', 'KO'])
print(backtest.summary_text())
```

Any object with the same methods as `DataCollector` can be passed as
`StockRanker(data_collector=...)`, for example `src.data.synthetic.SyntheticDataCollector`.

## How it works

1. **Fetch** two years of daily prices per stock from Yahoo Finance.
2. **Engineer features**: returns, volatility, moving-average distances, momentum,
   candlestick patterns and technical indicators. Each feature at day *t* uses only data
   up to *t*.
3. **Train** the ML ensemble once on the pooled history of every stock, using only
   scale-free features. Report accuracy on the most recent 20% of dates, then refit on
   everything.
4. **Score** each stock 0–100 on five components and combine them:

   | Component | Weight |
   |---|---|
   | Technical | 30% |
   | ML prediction | 25% |
   | Momentum | 20% |
   | Volume | 15% |
   | Sentiment | 10% |

5. **Rank**, label and export.

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the full design: component and
sequence diagrams, every scoring rule, the ML and backtest methodology, the
configuration reference, design decisions and known limitations.

## Configuration

Everything is in `config/config.yaml`: the symbol universe, history length, indicator
periods, model hyperparameters, score weights, filters, sentiment on/off, backtest
defaults and API rate limits. The
[configuration reference](docs/ARCHITECTURE.md#10-configuration-reference) explains
each setting.

Useful switches:

- `ranking_config.use_sentiment: false` skips news and sector requests (much faster).
- `ml_config.models.<model>.enabled: false` turns a model off.
- `ml_config.models.lstm.enabled: true` adds an LSTM (run `pip install tensorflow` first).

## Project structure

```
├── config/config.yaml              Settings
├── docs/ARCHITECTURE.md            Architecture and methodology
├── src/
│   ├── data/
│   │   ├── collector.py            Yahoo Finance access, caching, retries
│   │   ├── preprocessor.py         Cleaning, feature engineering, target
│   │   └── synthetic.py            Synthetic market for demo mode and tests
│   ├── analysis/
│   │   ├── technical_indicators.py Indicators and chart patterns
│   │   └── sentiment_analysis.py   News, VIX and sector sentiment
│   ├── models/
│   │   ├── ml_models.py            ML ensemble
│   │   └── evaluation.py           Metrics and reports
│   ├── prediction/stock_ranker.py  Scoring and ranking
│   ├── backtest/backtester.py      Walk-forward backtest
│   ├── utils/helpers.py            Utilities
│   └── cli.py                      Command-line interface
├── web/dashboard.py                Dash web dashboard
├── tests/                          Offline test suite
├── main.py                         Quick ranking of ten large caps
└── run_dashboard.py                Dashboard launcher
```

## Development

```bash
python -m pytest                          # offline suite, ~1.5 minutes
RUN_NETWORK_TESTS=1 python -m pytest      # also hit Yahoo Finance
```

The tests run on synthetic data, including two independent checks that the backtest
never uses future information. GitHub Actions runs them on Python 3.10, 3.12 and 3.13.

## Troubleshooting

- **`No data found for symbol`**: the ticker may be delisted or Yahoo may be throttling.
  The collector retries three times and then skips the symbol.
- **Analysis is slow**: around 100 stocks with sentiment takes several minutes because
  of rate limiting. Set `use_sentiment: false`, pass fewer `--symbols`, or raise
  `api_config.rate_limits.yfinance` carefully.
- **ML shows accuracy near 50%**: expected for next-day direction. Judge the system by
  the backtest's t-statistics, not raw accuracy.
- **`ModuleNotFoundError: src`**: run commands from the project root.

## Disclaimer

This software is for educational and research purposes. It does not provide
investment advice, past performance does not predict future results, and all
investing carries risk of loss. Backtests on today's index members suffer from
survivorship bias. Paper trade and do your own research before risking money.

## License

MIT
