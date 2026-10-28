# Ledger — stock and crypto outlook with the evidence attached

Ledger ranks US stocks and crypto by how likely each is to beat the rest of its
market over the next five days, builds a risk-aware portfolio from the top of
the ranking, and shows, before anything else, whether the model has proven any
skill on data it never saw.

It has two separate dashboards, **US Stocks** and **Crypto**, each with its own
models, settings, backtests and track record. The backend is Python (FastAPI)
and the frontend is Angular.

> **Educational and research use only. Not financial advice.** Short-term
> returns are close to random. Ledger is built to show you how much (or how
> little) evidence there is, not to promise profits.

## What it does

- **Ranks each universe** with a composite of a machine-learning ensemble
  (Random Forest, XGBoost, neural network), technical, momentum and volume
  scores, and news sentiment for stocks.
- **Measures itself honestly**: out-of-sample rank IC with a t-statistic,
  calibrated probabilities, and a plain verdict ("Indistinguishable from luck",
  "Some evidence of skill", …).
- **Explains every pick**: the signals on the chart and the model's per-feature
  contributions.
- **Builds a portfolio**: sector caps and inverse-volatility weights.
- **Forecasts volatility**, which is far more predictable than direction.
- **Backtests** walk-forward with purged retraining, transaction costs and
  attribution by score component.
- **Keeps a track record**: every analysis is stored before its outcome exists
  and scored automatically once its horizon has passed.
- **Flags unusual moves** twice a day (after the US open and close): big moves
  for an asset, volume spikes, gaps and market-wide moves, as in-app alerts.
- **Compares predictions with what happened**, so you can see which parts of
  the score help, and **runs experiments** with different settings, with a
  locked recent period to check that an improvement is real.
- **Runs offline in demo mode** on a simulated market.

## Quick start

### With Docker

```bash
docker compose up --build
```

Open http://localhost:8000. This runs in demo mode (simulated prices, no network
needed) and fills both dashboards on first start. For live Yahoo Finance data:

```bash
DEMO_MODE=false docker compose up --build
```

### Without Docker

Requires Python 3.10+ and Node 22+.

```bash
git clone https://github.com/elyr/stock-market-predictor.git
cd stock-market-predictor

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cd frontend && npm ci && npx ng build && cd ..

DEMO_MODE=true uvicorn api.main:app      # or without DEMO_MODE for live data
```

Open http://localhost:8000. API documentation is at http://localhost:8000/api/docs.

### Developing the frontend

```bash
uvicorn api.main:app --reload            # terminal 1, port 8000
cd frontend && npx ng serve              # terminal 2, http://localhost:4200 (proxies /api)
```

## Using the dashboards

Each dashboard (US Stocks, Crypto) has these pages:

| Page | What you get |
|---|---|
| **Outlook** | The evidence meter, the suggested portfolio with weights and reasons, the full ranking, and how the model was tested, including a calibration chart |
| **Backtest** | Run a walk-forward simulation with your settings; see returns vs. owning everything, per-component results and rank IC |
| **Track record** | Every past analysis scored against what actually happened |
| **Predicted vs actual** | Every prediction next to its outcome: decile staircase, which score parts help, skill over time, calibration, where it fails; CSV export |
| **Experiments** | Change weights, horizon or model settings, compare with the current setup, then check the winner once on a locked recent period |
| **Volatility** | Each asset's forecast volatility vs. its current level |
| **Alerts** | Unusual moves found at 09:45 and 16:15 New York time, newest first, with unread badges in the menu |

Click any symbol for its price chart, RSI, standing and reasons.

### Reading the numbers

| Number | Meaning | Good |
|---|---|---|
| Rank IC | correlation between the scores and what happened next, across assets | above 0.03 on average |
| t-statistic | whether a result is distinguishable from luck | above 2 (and above 3 to be convincing) |
| Chance to beat the field | calibrated probability the asset beats the universe average over the horizon | well-calibrated, not high |
| AUC | ranking accuracy; 0.5 is a coin flip | a few points above 0.5 is realistic |

## Command line

Everything also works without the web app:

```bash
python main.py --universe crypto                       # quick ranking
python src/cli.py analyze --universe stocks --top-n 10
python src/cli.py single --symbol ETH-USD --universe crypto
python src/cli.py backtest --universe crypto --cost-bps 15
python src/cli.py backtest --no-ml --days 250          # faster, rules only
python src/cli.py market
python src/cli.py config
```

Add `--demo` to any command to use simulated data.

## Python API

```python
from src.prediction import create_pipeline
from src.backtest import Backtester

crypto = create_pipeline('crypto')
result = crypto.get_top_10_recommendations(top_n=5)
print(result['top_10'][['Symbol', 'Composite_Score', 'ML_Probability', 'Weight']])
print(result['analysis_summary']['model_quality'])     # IC, AUC, calibration...

backtest = Backtester.from_config(crypto, test_days=180).run_symbols()
print(backtest.summary_text())
```

## How it works

1. **Data.** Two years of daily prices from Yahoo Finance per asset.
2. **Features.** Returns, volatility, moving averages, momentum, candlesticks,
   technical indicators, and asset-class features: performance relative to other
   stocks, or relative to Bitcoin (beta, correlation) for crypto.
3. **Target.** Does the asset beat its universe's average over the next five
   days? Removing the market's common move leaves what a ranking can predict.
4. **Model.** One ensemble per universe trained on every asset's history,
   evaluated on the most recent dates after a purge gap, calibrated, then refit
   on everything.
5. **Score and portfolio.** Weighted composite, top N with a sector cap and
   inverse-volatility weights.
6. **Accountability.** Backtests, and a track record scored on real outcomes.

Full design, diagrams and methodology: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Configuration

Everything is in `config/config.yaml`: each universe's symbols, filters and
portfolio rules; indicator periods; model settings, target and horizon; score
weights; backtest defaults; the daily scheduler. The
[configuration reference](docs/ARCHITECTURE.md#15-configuration-reference)
explains each setting.

Alert sensitivity and scan times are in the `signals` section; experiment
periods in `experiments`.

Server options are environment variables: `DEMO_MODE`, `DATABASE_PATH`,
`CONFIG_PATH`, `CORS_ORIGINS`, `SEED_DEMO`, `FRONTEND_DIST`.

## Project structure

```
├── api/                    FastAPI server: routes, jobs, persistence
├── frontend/               Angular app (two dashboards)
├── src/
│   ├── data/               Yahoo Finance access, features, synthetic market
│   ├── analysis/           Technical indicators, sentiment
│   ├── models/             Return ensemble, volatility model, evaluation
│   ├── prediction/         Stock and crypto pipelines, portfolio rules
│   ├── backtest/           Walk-forward backtest
│   └── cli.py              Command line
├── config/config.yaml      Settings
├── docs/ARCHITECTURE.md    Design and methodology
├── tests/                  Python tests (offline)
├── Dockerfile, docker-compose.yml
└── main.py                 Quick ranking from the terminal
```

## Development

```bash
python -m pytest                              # Python suite, offline (~2 min)
RUN_NETWORK_TESTS=1 python -m pytest          # plus live Yahoo Finance checks
cd frontend && npx ng test --watch=false      # Angular tests
```

The Python suite includes two independent checks that no prediction or backtest
uses future data. GitHub Actions runs both suites on every push.

## Deploying a public demo

The Docker image runs anywhere that hosts a container (Render, Railway, Fly.io,
Hugging Face Spaces, a VM). Use `DEMO_MODE=true` for a public demo: hosted
servers are often throttled by Yahoo Finance, and simulated data keeps the demo
reliable. GitHub Pages cannot host it, because the predictions need a Python
server.

## Disclaimer

For education and research. Not investment advice. Past performance, simulated
or real, does not predict future results. Backtests on today's index members
suffer from survivorship bias. Crypto assets are extremely volatile.

## License

MIT
