# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Forecast (#21): price ranges for the next day and week for every asset
  (50% and 90%), from a volatility estimate and calibrated past moves, centred
  on today's price. Every forecast is scored once its window has passed; the
  new **Forecast** page, a fan chart on asset pages, a Track record section and
  an Outlook column show the ranges and how often they held. Metrics and an
  alert watch the coverage.

### Added
- Model registry on MLflow (#5): every analysis that trains models records a
  new version with its settings, out-of-sample scores, git commit and model
  files. A **Models** page lists versions; promoting one pins it so analyses
  use it without retraining. Each stored analysis records its model version.
- Helm chart: an MLflow server with its own volume and web UI
  (`http://mlflow.localhost:8080`); the app waits for it before starting.
- Monitoring (#6): Prometheus metrics at `/metrics` (requests, jobs, data age,
  model skill on test dates and live outcomes, champion version); with
  `./kube.sh up --monitoring`, Prometheus with unit-tested alert rules and
  Grafana with a provisioned Ledger dashboard. `LOG_FORMAT=json` for
  structured logs (default on Kubernetes).
- Release flow (#7): the Release workflow builds the image once, scans it with
  Grype, and publishes it to GHCR with provenance and an SBOM; tags also
  publish the Helm chart (OCI) and a GitHub release. GitOps with Flux:
  `./kube.sh up --gitops` deploys from `deploy/gitops/`, which CI updates
  after each image it publishes.
- Backups (#9): `scripts/backup.py` writes a verified archive of the
  database, the model registry and the prediction results (consistent while
  the app runs; checksummed manifest; restore checks before replacing). A
  nightly CronJob keeps the newest 14; `./kube.sh backup` / `restore` and
  `./run.sh --backup` / `--restore`. CI runs a disaster drill on k3d.
- PostgreSQL and a job queue (#8): one schema for SQLite and PostgreSQL
  (SQLAlchemy Core, Alembic migrations, `DATABASE_URL`); jobs are rows in the
  database, run inline or by worker processes from a Redis queue
  (`JOB_QUEUE=redis`, `python -m api.worker`). `./kube.sh up --postgres` runs
  PostgreSQL, Redis, a worker and two servers with zero-downtime upgrades, and
  moves the data over; backups copy PostgreSQL too.

### Fixed
- The daily analysis scheduler (`scheduler.enabled`) had been removed by
  mistake and failed when turned on; it is back.

## [2.0.0] - 2026-10-29

Rebuilt as **Ledger**: a FastAPI and Angular app with separate stock and crypto
pipelines, an honest evaluation of every model, and one-command local and
Kubernetes deployments.

### Added
- Two dashboards, **US Stocks** and **Crypto**, each with its own models,
  settings, backtests and track record.
- Pooled cross-sectional models (Random Forest, XGBoost, neural network) with
  purged chronological splits, calibrated probabilities, rank IC and t-statistics,
  and per-pick explanations.
- Volatility forecasts, risk-aware portfolio construction (sector caps,
  inverse-volatility weights).
- Walk-forward backtests with costs and attribution; a track record scored on
  real outcomes.
- Market signal detection twice a day (US open and close) with in-app alerts.
- Predicted-versus-actual comparator and experiments with a locked period.
- `scripts/daily_prediction.py` and the **Daily prediction** workflow, which
  keeps each day's results as an artifact.
- `run.sh`: update from GitHub, install, build and start with one command.
- Kubernetes: Helm chart (`deploy/helm/ledger`), CronJobs for scans and the
  daily prediction, readiness endpoint, and `kube.sh` for a local k3d cluster.
- CI: Python 3.10/3.12/3.13 and Angular tests; Helm lint, manifest validation
  and an end-to-end deploy on k3d.
- Documentation: architecture and methodology, Kubernetes guide.

### Changed
- Demo mode runs fully offline on a simulated market.

## [1.0.0] - 2025-10-22

### Added
- First version: stock ranking with machine-learning models, technical analysis
  and a web dashboard.

[Unreleased]: https://github.com/elyr/stock-market-predictor/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/elyr/stock-market-predictor/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/elyr/stock-market-predictor/releases/tag/v1.0.0
