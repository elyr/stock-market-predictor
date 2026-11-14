# Ledger — stock and crypto outlook with the evidence attached

[![Tests](https://github.com/elyr/stock-market-predictor/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/elyr/stock-market-predictor/actions/workflows/tests.yml)
[![Kubernetes](https://github.com/elyr/stock-market-predictor/actions/workflows/kubernetes.yml/badge.svg?branch=main)](https://github.com/elyr/stock-market-predictor/actions/workflows/kubernetes.yml)
[![Daily analysis](https://github.com/elyr/stock-market-predictor/actions/workflows/daily-analysis.yml/badge.svg?branch=main)](https://github.com/elyr/stock-market-predictor/actions/workflows/daily-analysis.yml)
[![Release](https://img.shields.io/github/v/release/elyr/stock-market-predictor)](https://github.com/elyr/stock-market-predictor/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-3776AB?logo=python&logoColor=white)
![Angular](https://img.shields.io/badge/angular-22-DD0031?logo=angular&logoColor=white)
![Helm](https://img.shields.io/badge/helm-chart-0F1689?logo=helm&logoColor=white)

**Research tool, not financial advice.**

Ledger is a personal research and risk tool for someone who invests but is not
a market professional. Each week it tells you, in plain sentences, what
happened, how your portfolio did against simply buying the market, which risks
you are running, and what (if anything) to do. It ranks US stocks and crypto
by how likely each is to beat the rest of its universe, gives price ranges
with how often past ranges held, and stores every analysis so you can check it
against what really happened.

## What it is, and what it is not

- **It is** a way to see how much evidence there is for a ranking: out-of-sample
  rank IC with t-statistics, backtests after costs, a live track record, price
  ranges and volatility forecasts.
- **It is not** a source of buy or sell calls. Tests on real market data found
  **no signal that predicts returns**: the model has no measurable skill on
  stocks or coins at the 5-day horizon. Risk and volatility are far more
  predictable, so that is where most of the advice comes from. The only alert
  of its kind is a protection rule for coins, offered as protection, not as a
  prediction. Details: [docs/research/](docs/research/).
- Demo mode uses a simulated market with a planted signal, so it flatters the
  model. Demo results say nothing about real markets.

It has two separate dashboards, **US Stocks** and **Crypto**, each with its own
models, settings, backtests and track record. The backend is Python (FastAPI),
the frontend is Angular, and the full MLOps stack (PostgreSQL, Redis, MLflow,
Prometheus and Grafana, Helm, k3d, Flux) is part of the project.

## Quick start

```bash
git clone https://github.com/elyr/stock-market-predictor.git
cd stock-market-predictor
./run.sh                # simulated prices; add --live for real Yahoo Finance data
```

`run.sh` installs what is missing, builds the app, starts it at
http://127.0.0.1:8000 and opens your browser. Every run first updates from the
latest `main` (local changes are never overwritten). Demo and live data use
separate databases.

| Command | What it does |
|---|---|
| `./run.sh --live` | Real prices instead of simulated ones |
| `./run.sh --no-update` | Start the version you have, without checking GitHub |
| `./run.sh --docker` | Run in Docker instead of a local environment |
| `./run.sh --test` | Run the Python and web app test suites |
| `./run.sh --backup` / `--restore` | Back up this mode's data, or restore the newest backup |
| `./kube.sh up` | Local Kubernetes cluster (k3d + Helm), then http://ledger.localhost:8080 |
| `./kube.sh up --postgres --monitoring` | PostgreSQL, Redis job queue, Prometheus and Grafana |
| `./kube.sh up --gitops` | Let Flux deploy the images CI publishes |

`./run.sh --help` and `./kube.sh help` list every option. Docker Compose,
running without Docker and developing the frontend are in the
[guide](docs/GUIDE.md#running-it).

## The daily routine

1. Open the **Weekly brief** for your week in two minutes, ending with what to
   do (often: nothing).
2. Check the **evidence meter** on **Outlook** before trusting any ranking.
3. Record your trades under **My portfolio** to see your gains and risk against
   buying the market, with plain-language warnings.
4. Look at **Forecast** and **Volatility** for price ranges and how large the
   moves may be.
5. Once a day, `scripts/daily_analysis.py` (or the **Daily analysis**
   workflow, or `./kube.sh predict-now`) runs the analysis without a server and
   writes `report.md` and CSVs ([details](docs/GUIDE.md#daily-analysis-artifact)).
6. After a week, the **Track record** and **Predicted vs actual** pages score
   past analyses against what happened.

## Where alerts appear

Alerts show on the **Alerts** page, newest first, with unread badges in the
menu. Market signals (big moves, volume spikes, gaps, a broad selloff) are
scanned at 09:45 and 16:15 New York time. Protection alerts from the trend rule
are sent only in a universe whose own history shows the rule helps. Sensitivity
and scan times are in the `signals` section of `config/config.yaml`.

## Documentation

| Read | For |
|---|---|
| [docs/GUIDE.md](docs/GUIDE.md) | Features, every run path, the pages, the command line, configuration, project layout |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Design, methodology, configuration reference |
| [docs/research/](docs/research/) | What real market data showed, and what was ruled out |
| [docs/KUBERNETES.md](docs/KUBERNETES.md) | What the cluster runs and things to try |
| [docs/RELEASING.md](docs/RELEASING.md) | Releases and GitOps |
| [docs/presentation/Ledger.pptx](docs/presentation/Ledger.pptx) | A 12-slide overview |
| [AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md) | Rules for contributors and coding agents |
| [CHANGELOG.md](CHANGELOG.md), [SECURITY.md](SECURITY.md) | Changes and security reports |

## Disclaimer

For education and research. Not investment advice. Past performance, simulated
or real, does not predict future results. Backtests on today's index members
suffer from survivorship bias. Crypto assets are extremely volatile.

## License

[MIT](LICENSE)
