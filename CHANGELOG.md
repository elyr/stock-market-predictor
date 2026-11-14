# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- README shortened to under 150 lines (#69): what Ledger is and is not (it says plainly that tests on real data found no signal that predicts returns), quick start, the daily routine, where alerts appear and links to the docs. The detail moved, unchanged, to the new `docs/GUIDE.md` (features, every run path, pages, command line, configuration, project layout).
- Glossary applied to the code (#62), names only, no behaviour change: `StockRanker` is `AssetRanker` (`src/prediction/asset_ranker.py`), `rank_stocks` is `rank_assets`, `get_top_10_recommendations` is `analyse`, `save_recommendations` is `save_picks`, `StockPredictor` is `ReturnPredictor`, `fetch_stock_data` / `fetch_multiple_stocks` are `fetch_prices` / `fetch_many_prices`, `clean_stock_data` is `clean_price_data`, `recommendation_label` is `pick_label`. `scripts/daily_prediction.py` and `daily-prediction.yml` are now `daily_analysis.py` and `daily-analysis.yml` (workflow "Daily analysis", CronJob `<release>-daily-analysis`, artifact `daily-analysis-<date>`). CLI text says picks and analysis; saved CSVs are named `<universe>_picks_<time>.csv`. Kept on purpose: stored names, config and Helm value keys (`dailyPrediction`), the result keys `top_10` / `full_rankings` / `analysis_summary` and the `Recommendation` / `ML_Confidence` columns (they reach the API, so PR #63 renames them with aliases).
- Glossary applied to the UI and the API (#63). **Changes API output on purpose** (the `changes-output` label is set): responses now carry the glossary names next to the old ones. UI text says *analysis*, *score*, *pick* and *asset* only (no "run", "ideas", "prediction" for a score, "coin" or "stock" for an asset); the weekly brief's section is "Picks"; the Predicted-vs-actual page talks about scores; `models.ts` types only the new names. Fixtures, tests, README, ARCHITECTURE and the deck's speaker note follow. Pages are not merged or moved.

### Deprecated
Old API names stay for one release as aliases, then go (the new name is first):
- `analysis` (the analysis record in `GET /api/{universe}/analysis/latest`, `/analyses/{id}` and `/assets/{symbol}`) replaces `run`.
- `analyses` in `GET /api/{universe}/track-record` replaces `runs`.
- `GET /api/{universe}/analyses` and `/analyses/{id}` replace `/runs` and `/runs/{id}`.
- `GET /api/{universe}/performance/scores.csv` replaces `predictions.csv`; `summary.scores` in the performance report replaces `summary.predictions`.
- `model_agreement` replaces `ml_confidence`, and `pick_label` replaces `recommendation`, on every ranked asset.
- `picks` replaces `ideas` in the weekly brief's section (its title is now "Picks").
- `analysis_id` and `evaluated_analyses` in an analysis job's result replace `run_id` and `evaluated_runs`.
Stored names (tables, columns, config and Helm keys) are not renamed.

### Added
- Terminology check in CI (#65): `scripts/check_terms.py`, run by the Code job (and by `scripts/check.sh`), fails when a retired name from the Glossary returns in UI strings, API field names and routes, or Python identifiers. Its allowed exceptions are two short commented lists in the script (stored names, the deprecated API aliases, yfinance's own `Ticker`); research folders, `docs/` and this changelog are not scanned. Documented in `AGENTS.md` next to the size and unused-code check; tested in `tests/test_check_terms.py`.
- Skill apart from market risk in the backtest (#107): each strategy now reports its market sensitivity (beta to the equal-weight universe) and its return beyond market risk (alpha per year, with a t-statistic), as two new columns on the Backtest page. **Changes API output on purpose** (`metrics` rows of `GET /api/{universe}/backtests/{id}` gain `beta`, `alpha_per_year`, `alpha_t_stat`; the backtest snapshot changes). `docs/ARCHITECTURE.md` also records how the trend rule's record depends on the window (coins pass narrowly over 5 years, fail over 10).
- Protection alerts from the trend rule (#103): `src/signals/trend.py` replays "hold only while above 2 of the 50-, 100- and 200-day averages" on a universe's own history and sends `trend_exit` / `trend_enter` alerts only where that record cuts the worst drop by at least 25% for at most 2 points of return per year (`signals.trend` in `config.yaml`; expected to fail on stocks, pass on coins). The rule does not predict returns and the alerts say so. New `GET /api/{universe}/trend`; scans now fetch 5 years of prices while the rule is enabled. `api/main.py` and `models.ts` shed code to stay within the size limit (`models.ts` is now under it).
- Large-universe research (#97): `research/large/` and `docs/research/2026-11-large-universe.md` test the four signal families on about 1,480 stocks and 109 coins with tiered costs and a held-out last two years. Nothing passed; no app code changed.

### Fixed
- The track record's "Check for new results" job now reports `evaluated_analyses` (with `evaluated_runs` as the deprecated alias), the name the page reads since #110; before, the page always showed 0 new results. The CLI's pick panel says "model agreement" where it said "confidence".
- Scorecard workflow (#99): runs only while the repository is public and has `contents: read`, so it no longer fails on every run of a private repository.
- Data preparation (#100): an asset whose Volume column held integers and had zero-volume days failed with "Invalid value ... for dtype 'int64'" and was silently dropped (seen on `AAVE-USD`). Volume is now converted to float before zeros are replaced, for any asset.
- Release workflow (#95): the image job failed at the code-scanning upload, which cannot work in a private repository (code scanning is not enabled) or on Dependabot runs (read-only token). The upload is skipped in those cases; the image is still built and scanned, and critical findings with a fix still fail the job.

### Removed
- Unused code (#61): seven methods nothing called (`fetch_earnings_calendar`, `fetch_insider_transactions`, `save_data_to_csv`, both `clear_cache`, `find_support_resistance`, `has_forecasts`, `get_ml_prediction_score`) and 15 unused imports.
- `main.py` (#57): it duplicated `python src/cli.py analyze`, which takes the same `--universe` and `--demo` options. The CLI is the one command line.
- `src/models/evaluation.py` (#58): `ModelEvaluator` (521 lines) was created by the ranker but never called. Evaluation code now lives only in `src/evaluation/`.
- `src/utils/helpers.py` (#53): 19 of its 20 functions were unused or only tested. `recommendation_label` moved to `src/prediction/stock_ranker.py`, its only caller.
- News sentiment score (#54): it had weight 0, never ran, and could not be backtested. Removed with its `use_sentiment` setting, the daily script's `--no-sentiment` option, news fetching, the `sentiment_score` API field and the `textblob` dependency. See `docs/adr/0001-remove-sentiment.md`.

### Added
- Predictor review (#93): `docs/research/2026-11-predictor-review.md` records what real data shows about the predictor, what was ruled out and the plan; the scripts are in `research/`. `AGENTS.md` gains a Navigation table of entry points per kind of change.
- Code checks (#61): `scripts/check_code.py`, run by a new Code job in CI and by `scripts/check.sh`, fails on a Python or TypeScript file over 500 lines and on unused functions, methods, classes, imports or variables. Six files already over the limit are listed and may only shrink.
- Snapshot tests (#80): `tests/test_snapshots.py` runs fixed-seed stock and crypto analyses, a backtest and seven API responses, and compares them with snapshots recorded from the code before a change. A new Snapshots job in the Tests workflow records them from each pull request's base and compares, so refactors cannot change a number unnoticed (label `changes-output` for intended changes).
- Glossary (#50): `AGENTS.md` lists one name per concept for the UI, API, code and docs, with the names each one retires and how it is stored.
- Fallback price sources (#36): when Yahoo Finance fails for a symbol, crypto prices come from Coinbase's public candles (no key) and stock prices from Alpha Vantage when `ALPHA_VANTAGE_API_KEY` is set. `/metrics` counts series and failures per source, and the Outlook page says when part of an analysis came from a backup source. `api_config.fallback: false` turns it off.
- Long-term view (#35):
  - each analysis also trains a second model about a month ahead (21 trading days for stocks, 30 days for crypto), on the same inputs, with its own out-of-sample evidence;
  - a new **Long-term** page shows its ranking, whether it beats luck, and which effects history rewarded;
  - the weekly brief mentions its favourites;
  - the synthetic market can plant a slow signal (`alpha`) to test it.
- Next 3 days (#34):
  - every forecast now has a 3-day horizon (3 sessions for stocks, 72 hours for crypto) and a 70% range next to the 50% and 90% ones (migration 0005);
  - a new **Next 3 days** page shows each asset's 70% range, how often past ranges held and how the prediction is computed;
  - horizons can be configured per universe (`forecast_horizons`);
  - the track record and `/metrics` report 70% coverage.
- Weekly brief (#33): a new first page under Today with the week in plain sentences: the market, your portfolio, whether the model is working, ideas with their ranges and the alerts. It leads with what to do, and "nothing" is a valid answer. Built from Ledger's own data with fixed rules; downloadable as Markdown.
- My portfolio (#32):
  - record your buys and sells (transactions table, migration 0004);
  - see holdings at average cost, gains taken and not yet taken, and your value against a benchmark that received the same money on the same days;
  - a risk level and next week's likely value;
  - plain-language warnings when your own rules (`universes.<u>.risk`) are broken;
  - each holding with the model's view and its next-week range;
  - trades export as CSV.

### Changed
- `src/cli.py` (617 lines) keeps only the commands (230 lines); their tables and panels move to `src/cli_output.py` (#60). Output is unchanged.
- `StockRanker` is split by step (#56): `features.py` (data preparation), `training.py` (models, export and import) and `scoring.py` (component scores and the composite) next to `stock_ranker.py`, which keeps the settings and the ranking. 862 lines become four files under 420 lines; method bodies are unchanged.
- `api/service.py` (994 lines) is split into a package, `api/service/`, with one module per domain (#59): core (state and the analysis run), track record, forecasts, portfolio and brief, performance (backtests and experiments), and the model registry. Each is under 320 lines. `UniverseService` and its methods are unchanged.
- Fast test set (#55): tests that train models or run a backtest are marked `slow`. `pytest -m "not slow"` runs the rest in under a minute, and `scripts/check.sh --quick` now uses it instead of a hand-picked file list. CI still runs everything.
- One product name (#51): the log file is now `logs/ledger.log` (was `logs/stock_predictor.log`), and the CLI help and module docstrings say Ledger. Repository and image URLs keep the repository name.
- Presentation: a new "How to use it" slide with a simple routine for a non-expert, one overview slide for the architecture instead of two, and a title slide that states the goal (#47).
- The README and the presentation describe Ledger as a personal research assistant for a non-expert, honest about what can and cannot be predicted (#37).
- Evidence is counted honestly (#35): t-statistics on daily rank ICs now use the number of independent periods (dates divided by the horizon), because outcomes of consecutive days overlap. Reported t-statistics fall by about √5 for the 5-day model. The evidence meter's luck band uses the same count.

### Fixed
- Evidence of pinned models (#88): versions registered before t-statistics counted independent periods (#45) kept their old figure, which overstated it by about √horizon. Loading such a version, and the Models page, now divide its t-statistic by √horizon and add the effective count; for the live crypto champion that is 1.8 ("Indistinguishable from luck") instead of 4.0 ("Strong evidence of skill"). Exports also record their horizon.
- Backtest turnover is capped at 1, so rounding (1.0000000000000002) no longer fails `test_result_structure` on some days (#77).
- Track record (#31): only the latest analysis for each price date is scored and counted. Earlier runs on the same prices are kept, marked superseded, so one week no longer counts several times.

### Security
- Repository hardening (#39):
  - **Workflows:** read-only by default, actions pinned to commit SHAs, checkouts without stored credentials, inputs passed through the environment.
  - **New Security workflow:** gitleaks, pip-audit, npm audit and zizmor.
  - **OpenSSF Scorecard:** a new workflow rates the repository weekly.
  - **Dependabot** now also covers the presentation.
  - **API security headers,** including a Content Security Policy that allows the built app's inline script by its hash.

## [2.1.0] - 2026-11-02

### Added
- Project presentation (#29): `docs/presentation/Ledger.pptx`, 12 slides on what Ledger is, how it works and its goals. Generated from `build.js`; CI checks that it builds, and AGENTS.md asks for it to be updated whenever its content changes.
- Instructions for AI coding agents (#27):
  - `AGENTS.md`: project map, commands, the rules the results depend on, conventions, workflow, definition of done, known pitfalls.
  - `CLAUDE.md` imports it; `.github/copilot-instructions.md` points to it.
  - `.claude/settings.json` allows the routine test and build commands.
  - `scripts/check.sh` runs CI's local checks (`--quick` for the fast subset).
- Forecast (#21): price ranges for the next day and week for every asset
  (50% and 90%), from a volatility estimate and calibrated past moves, centred
  on today's price. Every forecast is scored once its window has passed; the
  new **Forecast** page, a fan chart on asset pages, a Track record section and
  an Outlook column show the ranges and how often they held. Metrics and an
  alert watch the coverage.
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

### Changed
- Dashboard usability (#25):
  - Navigation is grouped by purpose: Today, Is it working?, Improve it.
  - Pages lead with stat tiles: Outlook has an at-a-glance row and Backtest key-figure tiles.
  - Long explanations are collapsed or shortened.
  - Charts share a cleaner style.
  - Accessible "?" help tooltips explain every major figure, column and chart, from one glossary.
  - The experiments form offers the new model's settings.
  - A backtest without the model now ranks on the rule-based scores.
- Return model (#23): a cross-sectional model replaces the hand-weighted
  composite and the 86-feature classifier ensemble. Ten ranked features with a
  known rationale (reversal, 12-month momentum, low volatility and beta,
  distance from the 20-day average, 52-week high, lottery returns, volume
  shocks), residual returns, a risk-adjusted target and a ridge regression.
  On the demo market the out-of-sample IC rose from 0.009 to 0.076. Stocks now
  fetch 5 years of history and backtests cover about a year. The earlier model
  stays available as `ml_config.model: legacy`.

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

[Unreleased]: https://github.com/elyr/stock-market-predictor/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/elyr/stock-market-predictor/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/elyr/stock-market-predictor/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/elyr/stock-market-predictor/releases/tag/v1.0.0
