# Ledger — stock and crypto outlook with the evidence attached

[![Tests](https://github.com/elyr/stock-market-predictor/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/elyr/stock-market-predictor/actions/workflows/tests.yml)
[![Kubernetes](https://github.com/elyr/stock-market-predictor/actions/workflows/kubernetes.yml/badge.svg?branch=main)](https://github.com/elyr/stock-market-predictor/actions/workflows/kubernetes.yml)
[![Daily prediction](https://github.com/elyr/stock-market-predictor/actions/workflows/daily-prediction.yml/badge.svg?branch=main)](https://github.com/elyr/stock-market-predictor/actions/workflows/daily-prediction.yml)
[![Release](https://img.shields.io/github/v/release/elyr/stock-market-predictor)](https://github.com/elyr/stock-market-predictor/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-3776AB?logo=python&logoColor=white)
![Angular](https://img.shields.io/badge/angular-22-DD0031?logo=angular&logoColor=white)
![Helm](https://img.shields.io/badge/helm-chart-0F1689?logo=helm&logoColor=white)

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
- **Versions every model** in an MLflow model registry: each prediction is
  traceable to the model that made it, and you can roll back to an earlier one.
- **Is monitored**: Prometheus metrics at `/metrics` (requests, jobs, data age,
  model skill), a Grafana dashboard and alert rules on Kubernetes.
- **Runs offline in demo mode** on a simulated market.

## Quick start

### One command (Linux)

```bash
git clone https://github.com/elyr/stock-market-predictor.git
cd stock-market-predictor
./run.sh                # simulated prices; add --live for real Yahoo Finance data
```

`run.sh` does everything: it installs what is missing (on Arch-based systems
such as CachyOS it asks for your password once, elsewhere it tells you what to
install), builds the app, starts it at http://127.0.0.1:8000 and opens your
browser. Press Ctrl+C to stop.

**Every run first updates from GitHub.** It fetches the latest `main`,
fast-forwards to it and rebuilds only what changed, then replaces the copy it
started last time. So after merging a pull request on GitHub (for example one
made with Claude in the cloud), just run `./run.sh` again. Local changes are
never overwritten: if there are any, the update is skipped with a message.

| Command | What it does |
|---|---|
| `./run.sh` | Update, build, start in demo mode (simulated prices) |
| `./run.sh --live` | The same with real prices |
| `./run.sh --branch NAME` | Follow another branch, e.g. to try a pull request before merging |
| `./run.sh --no-update` | Start the version you have, without checking GitHub |
| `./run.sh --docker` | Run in Docker instead of a local environment |
| `./run.sh --test` | Run the Python and web app test suites |
| `./run.sh --help` | All options |

Demo and live data are kept in separate databases, so switching never mixes them.

### On Kubernetes (local cluster with Helm)

```bash
./kube.sh up            # then open http://ledger.localhost:8080
```

`kube.sh` creates a local Kubernetes cluster in Docker (k3d), builds the image,
deploys the Helm chart in `deploy/helm/ledger` and opens the browser. Alert
scans and the daily prediction run as Kubernetes CronJobs; the data lives on
persistent volumes. Like `run.sh`, it updates from GitHub first.

| Command | What it does |
|---|---|
| `./kube.sh up [--live] [--profile desktop] [--monitoring]` | Update, build, deploy or upgrade, open the browser |
| `./kube.sh status` / `logs` | What is running / follow the server's logs |
| `./kube.sh predict-now` / `results` | Run the daily prediction now / copy its results to `./results` |
| `./kube.sh test` | Run the chart's tests (`helm test`) |
| `./kube.sh down` / `destroy` | Remove the app, keeping its data / delete the cluster |

It also runs an MLflow server for the model registry, at
http://mlflow.localhost:8080. With `./kube.sh up --monitoring`, Prometheus and
Grafana come too, with a ready-made dashboard and alert rules
(http://grafana.localhost:8080).

What gets deployed, the design choices and things to try:
**[docs/KUBERNETES.md](docs/KUBERNETES.md)**.

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
| **Models** | Every trained model version with its out-of-sample scores; roll back to (pin) an earlier one, or resume retraining |
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

## Daily prediction artifact

`scripts/daily_prediction.py` runs the day's prediction on its own (no server,
no database) and writes the results to a folder:

```bash
python scripts/daily_prediction.py                     # both universes, live data
python scripts/daily_prediction.py --demo --limit 20   # simulated prices, about a minute
```

It saves `report.md` (picks, model quality, checks), each universe's picks and
full ranking as CSV, model details as JSON, and `run.json`. It also checks the
output (data downloaded, prices recent, weights add up, scores in range) and
exits with code 1 if anything fails, while still writing the files.

The **Daily prediction** workflow (`.github/workflows/daily-prediction.yml`) is
separate from the tests. It runs every day at 21:30 UTC (stocks on weekdays,
crypto every day) and can also be started from the Actions tab. Its results
are saved as an artifact for 90 days: open a run and download it under
"Artifacts". The report also appears on the run's summary page.

## Model registry

Each analysis that trains models saves them as a new version in MLflow, with
the settings, the out-of-sample scores, the git commit and the model files.
The **Models** page lists the versions; making an earlier one the champion
pins it, and analyses then use it without retraining until you resume.

With `./run.sh` the registry is a SQLite file in `data/`. To browse it in
MLflow's own interface:

```bash
uvx mlflow ui --backend-store-uri sqlite:///data/mlflow-demo.db   # or mlflow-predictions.db for live data
```

On Kubernetes, `kube.sh` deploys an MLflow server with its UI at
http://mlflow.localhost:8080. Details: [architecture, §11c](docs/ARCHITECTURE.md#11c-model-registry).

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
`CONFIG_PATH`, `CORS_ORIGINS`, `SEED_DEMO`, `FRONTEND_DIST`,
`MODEL_REGISTRY` (`off` to turn the registry off), `MLFLOW_TRACKING_URI`
(default: a SQLite file next to the database), `MLFLOW_UI_URL`,
`LOG_FORMAT` (`json` for one JSON object per line), `LOG_LEVEL`,
`INTERNAL_SCHEDULER` (set to `false` when an outside scheduler such as
Kubernetes CronJobs runs the alert scans).

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
├── scripts/                Daily prediction, Kubernetes job trigger, shared shell helpers
├── deploy/helm/ledger/     Helm chart (Kubernetes)
├── config/config.yaml      Settings
├── docs/                   ARCHITECTURE.md (design), KUBERNETES.md (cluster guide)
├── tests/                  Python tests (offline)
├── Dockerfile, docker-compose.yml
├── run.sh, kube.sh         One-command start: local, or on a local Kubernetes cluster
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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the rules the code relies on,
and how pull requests are checked. Changes are listed in
[CHANGELOG.md](CHANGELOG.md); security reports go through
[SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
