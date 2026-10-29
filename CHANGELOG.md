# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
