# Using Ledger

Detail moved out of the [README](../README.md): what Ledger does, every way to run it, the pages, the command line, configuration and the project layout.

## What it does

- **Ranks each universe** with a cross-sectional model: ten well-known effects
  (short-term reversal, 12-month momentum, low volatility, 52-week high, …),
  ranked against the other assets each day, combined by a ridge regression
  that learns from history which way each one points.
- **Measures itself honestly**: out-of-sample rank IC with a t-statistic,
  calibrated probabilities, and a plain verdict ("Indistinguishable from luck",
  "Some evidence of skill", …).
- **Explains every pick**: the signals on the chart and the model's per-feature
  contributions.
- **Builds a portfolio**: sector caps and inverse-volatility weights.
- **Forecasts volatility**, which is far more predictable than direction.
- **Looks a month ahead** with a second model, where textbook effects
  (momentum, low volatility, 52-week high) have more room to show, with its own
  evidence.
- **Follows your own portfolio**: record your trades and see your gains, risk
  and warnings in plain language, compared with simply buying the market.
- **Writes you a weekly brief**: the week in plain sentences, ending with what to
  do, built from Ledger's own numbers with fixed rules.
- **Shows where prices may be** over the next day, the next 3 days and the next
  week as ranges (likely half the time, 7 times in 10 and 9 times in 10), with
  how often past ranges held.
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
- **Keeps working when Yahoo Finance fails**: crypto prices fall back to
  Coinbase, and stocks to Alpha Vantage when you give it a free key.
- **Runs offline in demo mode** on a simulated market.

## Running it

### `run.sh` (Linux)

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
| `./run.sh --backup` / `--restore` | Back up this mode's data to `backups/`, or restore the newest backup |
| `./run.sh --help` | All options |

Demo and live data are kept in separate databases, so switching never mixes them.

### On Kubernetes (local cluster with Helm)

```bash
./kube.sh up            # then open http://ledger.localhost:8080
```

`kube.sh` creates a local Kubernetes cluster in Docker (k3d), builds the image,
deploys the Helm chart in `deploy/helm/ledger` and opens the browser. Alert
scans and the daily analysis run as Kubernetes CronJobs; the data lives on
persistent volumes. Like `run.sh`, it updates from GitHub first.

| Command | What it does |
|---|---|
| `./kube.sh up [--live] [--profile desktop] [--monitoring]` | Update, build, deploy or upgrade, open the browser |
| `./kube.sh up --gitops` | Let Flux deploy the images CI publishes, from git |
| `./kube.sh up --postgres` | PostgreSQL, a Redis job queue with a worker, two servers with zero-downtime upgrades |
| `./kube.sh status` / `logs` | What is running / follow the server's logs |
| `./kube.sh predict-now` / `results` | Run the daily analysis now / copy its results to `./results` |
| `./kube.sh test` | Run the chart's tests (`helm test`) |
| `./kube.sh backup` / `restore` | Back up the data now (nightly anyway) / restore a backup |
| `./kube.sh down` / `destroy` | Remove the app, keeping its data / delete the cluster |

It also runs an MLflow server for the model registry, at
http://mlflow.localhost:8080. With `./kube.sh up --monitoring`, Prometheus and
Grafana come too, with a ready-made dashboard and alert rules
(http://grafana.localhost:8080).

`./kube.sh up --gitops` hands deployment to **Flux**: after each merge, CI
publishes a scanned image to GHCR and records its tag in git, and Flux deploys
it ([RELEASING.md](RELEASING.md)).

What gets deployed, the design choices and things to try:
**[KUBERNETES.md](KUBERNETES.md)**.

### With Docker

```bash
docker compose up --build
```

Open http://localhost:8000. This runs in demo mode (simulated prices, no network
needed) and fills both dashboards on first start. For live Yahoo Finance data:

```bash
DEMO_MODE=false docker compose up --build
```

If Yahoo Finance fails for a symbol, crypto prices come from Coinbase (no key
needed). For stocks, set a free [Alpha Vantage](https://www.alphavantage.co/support/#api-key)
key first: `export ALPHA_VANTAGE_API_KEY=…` (it covers about 25 symbols a day).
`./run.sh`, `./kube.sh` and Docker Compose pass it on.

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

### Where the data lives

Every run path uses one of two shapes. **One process** is SQLite with jobs run
inside the server. **Scaled out** is PostgreSQL with a Redis job queue and
worker processes. Jobs themselves are rows in the database; Redis carries only
their ids, so the scaled shape needs a Redis service as well as PostgreSQL.

| Run path | Database | Jobs | Model registry (MLflow) |
|---|---|---|---|
| `./run.sh` (demo) | SQLite `data/demo.db` | in the server | SQLite file next to the database (`data/mlflow-demo.db`) |
| `./run.sh --live` | SQLite `data/predictions.db` | in the server | `data/mlflow-predictions.db` |
| `./run.sh --docker`, `docker compose up` | SQLite `demo.db` (`predictions.db` with `--live`) on the `ledger-data` volume | in the server | SQLite file next to the database, on the same volume |
| `uvicorn api.main:app` | `DATABASE_PATH`, else `tracking.database` in the config (`data/predictions.db`) | in the server | SQLite file next to the database |
| `./kube.sh up` | SQLite on a persistent volume, one server | in the server | MLflow server in the cluster |
| `./kube.sh up --postgres` | PostgreSQL in the cluster | Redis queue, one worker, two servers | MLflow server in the cluster |
| `./kube.sh up --gitops` | as the two rows above, from the chart values in git | as above | as above |
| `python src/cli.py`, `scripts/daily_analysis.py` | none (results are printed or written as files) | none | none |

Set `DATABASE_URL` to use PostgreSQL and `JOB_QUEUE=redis` with `REDIS_URL` to
queue jobs for workers (`python -m api.worker`); see
[design/operations.md](design/operations.md#11e-database-jobs-and-scaling-out).
The test suite uses SQLite and runs jobs in-process; with `TEST_DATABASE_URL`
and `TEST_REDIS_URL` set (the `backend-postgres` CI job) it also runs against
PostgreSQL and Redis.

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
| **Weekly brief** | Your week in two minutes, in plain sentences: what the market did, how your portfolio did, whether the model is working, a few picks with their ranges, the alerts, and what to do (often: nothing). Downloadable as Markdown |
| **Long-term** | The ranking for about a month ahead from a second model, its own evidence (is it better than luck?), and which effects history rewarded |
| **My portfolio** | Record your buys and sells; see what you hold, your gains, how you did against the market with the same money, your risk level, next week's likely value, and plain-language warnings when your own rules are broken |
| **Next 3 days** | Where each price should be in 3 days, 7 times in 10, how often such ranges held, and how the prediction is computed, in plain steps |
| **Forecast** | Every asset's price now and its likely range for the next day, 3 days and the next week, with how often past ranges held; a fan chart on each asset's page |
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
python src/cli.py analyze --universe stocks --top-n 10
python src/cli.py single --symbol ETH-USD --universe crypto
python src/cli.py backtest --universe crypto --cost-bps 15
python src/cli.py backtest --no-ml --days 250          # faster, rules only
python src/cli.py market
python src/cli.py config
```

Add `--demo` to any command to use simulated data.

## Daily analysis artifact

`scripts/daily_analysis.py` runs the day's prediction on its own (no server,
no database) and writes the results to a folder:

```bash
python scripts/daily_analysis.py                     # both universes, live data
python scripts/daily_analysis.py --demo --limit 20   # simulated prices, about a minute
```

It saves `report.md` (picks, model quality, checks), each universe's picks and
full ranking as CSV, model details as JSON, and `run.json`. It also checks the
output (data downloaded, prices recent, weights add up, scores in range) and
exits with code 1 if anything fails, while still writing the files.

The **Daily analysis** workflow (`.github/workflows/daily-analysis.yml`) is
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
http://mlflow.localhost:8080. Details: [architecture, §11c](design/operations.md#11c-model-registry).

## Python API

```python
from src.prediction import create_pipeline
from src.backtest import Backtester

crypto = create_pipeline('crypto')
result = crypto.analyse(top_n=5)
print(result['top_10'][['Symbol', 'Composite_Score', 'ML_Probability', 'Weight']])
print(result['analysis_summary']['model_quality'])     # IC, AUC, calibration...

backtest = Backtester.from_config(crypto, test_days=180).run_symbols()
print(backtest.summary_text())
```

## How it works

1. **Data.** Two years of daily prices from Yahoo Finance per asset, with
   Coinbase and Alpha Vantage as fallbacks.
2. **Features.** Ten well-known effects (short-term reversal, momentum, low
   volatility, low beta, 52-week high, …), computed on each asset's return
   after removing the market's common move, and ranked against the other
   assets each day.
3. **Target.** Does the asset beat the rest of its universe over the next five
   days (and, for the long-term model, the next month)?
4. **Model.** A ridge regression per universe trained on every asset's history,
   evaluated on the most recent dates after a purge gap, with t-statistics
   that count only independent periods, calibrated, then refit on everything.
5. **Score and portfolio.** Weighted composite, top N with a sector cap and
   inverse-volatility weights.
6. **Accountability.** Backtests, and a track record scored on real outcomes.


Full design and methodology: [ARCHITECTURE.md](ARCHITECTURE.md). A 12-slide overview: [presentation/Ledger.pptx](presentation/Ledger.pptx).

## Configuration

Everything is in `config/config.yaml`: each universe's symbols, filters and
portfolio rules; indicator periods; model settings, target and horizon; score
weights; backtest defaults; the daily scheduler. The
[configuration reference](design/reference.md#15-configuration-reference)
explains each setting.

Alert sensitivity and scan times are in the `signals` section; experiment
periods in `experiments`.

Server options are environment variables: `DEMO_MODE`, `DATABASE_PATH`,
`CONFIG_PATH`, `CORS_ORIGINS`, `SEED_DEMO`, `FRONTEND_DIST`,
`DATABASE_URL` (PostgreSQL instead of SQLite), `JOB_QUEUE` (`redis` to run
jobs in worker processes: `python -m api.worker`) with `REDIS_URL`,
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
│   ├── analysis/           Technical indicators
│   ├── models/             Return ensemble, volatility model
│   ├── prediction/         Stock and crypto pipelines, portfolio rules
│   ├── backtest/           Walk-forward backtest
│   └── cli.py              Command line
├── scripts/                Daily analysis, Kubernetes job trigger, shared shell helpers
├── deploy/helm/ledger/     Helm chart (Kubernetes)
├── config/config.yaml      Settings
├── deploy/gitops/          Flux: what the cluster runs, from git
├── docs/                   ARCHITECTURE.md (map, design/ detail, adr/ decisions), KUBERNETES.md (cluster), RELEASING.md (releases, GitOps),
│                           presentation/ (the project deck, generated by build.js)
├── tests/                  Python tests (offline)
├── Dockerfile, docker-compose.yml
└── run.sh, kube.sh         One-command start: local, or on a local Kubernetes cluster
```

## Development

```bash
python -m pytest                              # Python suite, offline (~2 min)
RUN_NETWORK_TESTS=1 python -m pytest          # plus live Yahoo Finance checks
cd frontend && npx ng test --watch=false      # Angular tests
```

The Python suite includes two independent checks that no prediction or backtest
uses future data. GitHub Actions runs both suites on every push; the
Kubernetes and Release workflows check the chart, the deployments and the
image. How releases work: [RELEASING.md](RELEASING.md).

## Deploying a public demo

The Docker image runs anywhere that hosts a container (Render, Railway, Fly.io,
Hugging Face Spaces, a VM). Use `DEMO_MODE=true` for a public demo: hosted
servers are often throttled by Yahoo Finance, and simulated data keeps the demo
reliable. GitHub Pages cannot host it, because the predictions need a Python
server.
