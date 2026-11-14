# AGENTS.md

Instructions for AI coding agents (and a fast orientation for people) working on
**Ledger**. `CLAUDE.md` and `.github/copilot-instructions.md` point here, so this
file is the one to keep up to date.

Ledger ranks US stocks and crypto by how likely each is to beat the rest of its
universe over the next few days, and shows honestly how much evidence there is
for that: out-of-sample rank IC with t-statistics, backtests, a live track
record, price ranges and volatility forecasts. It is also a learning vehicle for
an end-to-end MLOps stack (FastAPI, Angular, PostgreSQL, Redis/RQ, MLflow,
Prometheus/Grafana, Helm, k3d, Flux, GHCR). Read `docs/ARCHITECTURE.md` (the map) before
any non-trivial change; the detail is in `docs/design/` and the reasons are in `docs/adr/`.

## Map

| Path | What lives there |
|---|---|
| `src/data/` | Yahoo Finance collector with fallback sources (`providers.py`: Coinbase, Alpha Vantage), cleaning and features (`preprocessor.py`), synthetic market for demo and tests (`synthetic.py`) |
| `src/models/cross_section.py` | **The return model**: residual returns, ten ranked `XS_*` features, `Target_XS`, ridge (+ optional XGBoost), calibration |
| `src/models/ml_models.py` | Purged split, IC, reliability table; the `legacy` classifier ensemble |
| `src/models/volatility.py`, `forecast.py` | Volatility model; price ranges (split-conformal) for the Forecast page |
| `src/personal/brief.py` | The weekly brief: rule-based plain sentences and what to do |
| `src/personal/portfolio.py` | Your portfolio: holdings from transactions, history against a cash-flow-matched benchmark, risk warnings |
| `src/prediction/` | `AssetRanker` (shared pipeline, `asset_ranker.py`) assembled from its steps (`features.py`, `training.py`, `scoring.py`), `StockPipeline` / `CryptoPipeline`, portfolio rules |
| `src/backtest/`, `src/evaluation/` | Walk-forward backtester; predicted-vs-actual report; experiments and the lockbox |
| `api/` | FastAPI app (`main.py`), per-universe service (`service/`, one module per domain), store and SQLAlchemy tables (`store.py`, `db.py`), Alembic migrations, jobs (in-process or RQ), Prometheus metrics |
| `frontend/src/app/` | Angular 22: `pages/` (one per menu entry), `shared/` (chart, hint, evidence meter, score bar), `core/` (API client, stores, types, `format.ts`, `glossary.ts`) |
| `config/config.yaml` | Universes, model, ranking weights, backtest, experiments, signals, scheduler |
| `deploy/helm/ledger`, `deploy/gitops` | Helm chart (with Prometheus alert rules in `files/`), Flux manifests |
| `run.sh`, `kube.sh` | One-command local run (venv or Docker) and k3d deployment; both fetch the latest `main` |
| `tests/` | pytest suite (offline); `tests/prometheus/` holds promtool tests for the alert rules |
| `research/`, `docs/research/` | One-off research scripts on real market data and their findings; not part of the app or its tests |
| `docs/ARCHITECTURE.md`, `docs/design/`, `docs/adr/` | The map (diagram, module map, rules, CI checks, decisions); the detail by topic (section numbers are stable); one short file per decision |
| `docs/presentation/` | The project presentation: `build.js` generates `Ledger.pptx` (see Presentation below) |

## Navigation

Open these first; read `docs/ARCHITECTURE.md`, then the `docs/design/` file for the area you change.

| To change | Start at | Then |
|---|---|---|
| What an analysis computes | `AssetRanker.rank_assets` and `analyse` (`src/prediction/asset_ranker.py`) | steps in `features.py`, `training.py`, `scoring.py`; universe overrides in `pipelines.py` |
| A model input or the target | `add_cross_section_features` (`src/models/cross_section.py`) | rule 1 above; both signal tests in `tests/test_cross_section.py` |
| A data source | `DataCollector.fetch_prices` and `_fallback` (`src/data/collector.py`) | `providers.py`; mirror the method in `SyntheticDataCollector` |
| An alert rule | `SignalDetector.scan` (`src/signals/detector.py`), returning `Signal` objects | thresholds in `config.yaml` `signals`; `tests/test_signals.py` |
| The trend rule, its record or accuracy bar | `trend_state`, `rule_record`, `trend_verdict` (`src/signals/trend.py`) | `SignalDetector.trend_report` and `_trend_signals`; `signals.trend` in `config.yaml`; `UniverseService.trend_view` (`api/service/core.py`); `tests/test_trend.py` |
| How alerts are delivered | `Notifier.publish` and `NotificationChannel` (`api/notifications.py`) | scan entry: `scan_signals` in `api/service/core.py` |
| An API route | `create_app` (`api/main.py`) | the method in `api/service/<domain>.py`; background work in `api/tasks.py` and `api/jobs.py` |
| An API response shape | the service method | `frontend/src/app/core/models.ts`, the fixture in `frontend/src/testing/fixtures/`, `tests/test_api.py` |
| A page | `frontend/src/app/pages/<page>.ts` | route in `app.routes.ts`, menu in `app.ts`, tooltips in `core/glossary.ts`, the presentation |
| A stored table | `api/db.py` (table and `TABLES`) | a migration in `api/migrations/versions/`, queries in `api/store.py` |
| A backtest or its metrics | `Backtester.run` and `_metrics` (`src/backtest/backtester.py`) | `serialize_backtest` in `api/service/performance.py` |
| A user-tunable setting | `config/config.yaml` | `ALLOWED_SETTINGS` (`src/evaluation/experiments.py`), its fixture, `pages/experiments.ts` |

What is known about the predictor on real data, what was ruled out and the
plan: `docs/research/2026-11-predictor-review.md` (scripts in `research/`).
Read it before any work on signals, models or alerts.

## Glossary

One name per concept, in the UI, the API, the code and the docs. Use the name in
the first column; the last column lists the names it retires. Storage names
(tables, columns, migrations) are not renamed, so the "Stored as" column maps
them. UI tooltip definitions for non-specialists live separately, in
`frontend/src/app/core/glossary.ts`.

| Term | Meaning | Stored as | Retired names |
|---|---|---|---|
| **Ledger** | The product. The repository name appears only in install instructions. | | stock-market-predictor, stock predictor |
| **universe** | A set of assets analysed together: `stocks` or `crypto`. Universes never share models or data. | `universe` | market (for this sense) |
| **asset** | One stock or coin in a universe. | | ticker, stock (when crypto is included), coin |
| **symbol** | An asset's identifier, such as `AAPL` or `BTC-USD`. | `symbol` | ticker |
| **analysis** | One computation over a universe on one price date: features, models, scores, forecasts and evidence. | `runs` table, `run_id` | run, prediction run, daily prediction |
| **horizon** | How far ahead a model or forecast looks: *3 days*, *next week* (5 trading days or 7 days) or *long-term* (21 trading days or 30 days). | `horizon` | period, window (for this sense) |
| **score** | The model's raw output for one asset in one analysis; rankings use it. | `predictions` table, `composite_score` | prediction, signal (for this sense) |
| **probability** | The calibrated chance that an asset beats its universe; shown, never used to rank. | `ml_probability` | confidence |
| **ranking** | The assets of an analysis ordered by score. | | leaderboard |
| **pick** | An asset near the top of the ranking that Ledger suggests looking at. | `picked` | idea, recommendation, buy signal |
| **forecast** | A predicted price range (50%, 70% or 90%) for one asset and one horizon. | `forecasts`, `forecast_batches` | prediction (for this sense), projection |
| **volatility forecast** | The predicted size of price moves, not their direction. | | risk forecast |
| **evidence** | Out-of-sample proof that the scores work: rank IC, t-statistic, luck band. | | proof, accuracy (for this sense) |
| **backtest** | A simulated history of trading the picks, after costs. | `backtests` | simulation |
| **track record** | Past analyses scored against what really happened once their horizon has passed. | | live performance, history |
| **trend rule** | Hold an asset only while its price is above at least 2 of its 50-, 100- and 200-day averages. It does not predict returns; it is offered only as protection, and only in a universe whose own history shows it cuts the worst drop without giving up return (`signals.trend` in `config.yaml`). | `signals.trend` config, `trend_exit` / `trend_enter` notifications | trend signal, moving-average strategy |
| **protection alert** | An **alert** from the trend rule when an asset's state changes (`trend_exit`: move to cash; `trend_enter`: trend is back up). Sent only in a universe that passes the accuracy bar, and always states the rule's record. | `notifications` | sell signal, exit signal |
| **market signal** | A rule-based event in the prices or an analysis (a big move, unusual volume, a gap, a broad selloff, a changed set of picks) that raises an **alert**. | `signals` config, `notifications` | signal (alone), warning |

## Commands

Run from the repository root. Times are on a typical laptop.

```bash
pip install -r requirements.txt                 # Python 3.10–3.13
python3 -m pytest -q                            # full suite, ~8–10 min (slow: trains models)
python3 -m pytest -q -m "not slow"              # fast set, under 1 min: run this while you work
python3 -m pytest -q tests/test_cross_section.py tests/test_forecast.py   # one area, slow tests included
TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres python3 -m pytest -q tests/test_store_backends.py
                                                # store tests also on PostgreSQL (CI does this)
cd frontend && npm ci && npx ng test --watch=false && npx ng build   # ~10 s tests, ~15 s build
scripts/check.sh --quick                        # fast Python tests + frontend tests and build
scripts/check.sh                                # everything CI runs that works without a cluster
DEMO_MODE=true uvicorn api.main:app --port 8000 # demo server: synthetic prices, seeds both dashboards (~2 min)
```

The full Python suite is slow; run the fast set (`-m "not slow"`) while you
work, then the full suite once before opening the PR. Before a refactor, record the analysis output on `main`
(`UPDATE_SNAPSHOTS=1 python3 -m pytest -q tests/test_snapshots.py`), then run
`tests/test_snapshots.py` on your change: it must still pass. CI does the same
(the Snapshots job); label a PR `changes-output` when it changes the numbers on
purpose. Mark a new test
`@pytest.mark.slow` when it trains models or runs a backtest (2 s or more), or
when it depends on what an earlier slow test stored.

## Rules the results depend on

Reviews check these first. Breaking one silently makes every number in the app wrong.

1. **No future information.** A feature at date *t* uses data up to *t*. Targets
   (`Future_*`, `Target_*`) are excluded from features by name
   (`NON_FEATURE_COLUMNS`, the `XS_` prefix check in `select_feature_columns`).
   A new target column must be added there. Training rows need labels known at
   decision time (purge gap = horizon).
2. **Stocks and crypto stay separate**: separate pipeline instances, models,
   settings, stored runs and registry entries.
3. **Evaluate honestly**: chronological purged splits, rank IC with t-statistics,
   after-cost backtests. Do not tune on the lockbox period.
4. **Rank on the model's raw score, never the calibrated probability** (a
   calibrator with a negative slope would reverse the order).
5. **Tests stay offline**: use `SyntheticDataCollector` (`reversal=0.2` plants a
   known signal; `0.0` has none). Mark live-data tests `@pytest.mark.network`.
6. **A model change needs both directions tested**: it must find the planted
   signal *and* find nothing on a market without one (see `tests/test_cross_section.py`).
   The synthetic market plants a fast signal (`reversal`) and a slow one (`alpha`).
7. **Count independent periods.** Outcomes over *h* days overlap from day to
   day, so t-statistics on daily ICs use `information_coefficient(…, overlap=h)`.

## Conventions

**Python.** Type hints and docstrings, PEP 8. Config changes go in
`config/config.yaml` *and*, when user-tunable, in `ALLOWED_SETTINGS`
(`src/evaluation/experiments.py`).

**Database.** Schema changes need an Alembic migration in
`api/migrations/versions/` (next number, `down_revision` = previous), the table
in `api/db.py` and in its `TABLES` list (backups use it). Store code must work on
SQLite and PostgreSQL.

**API ↔ frontend.** Response shapes are typed in `frontend/src/app/core/models.ts`.
Frontend tests use recorded responses in `frontend/src/testing/fixtures/`.
When an API response changes, update the matching fixture. For example, after
changing `ALLOWED_SETTINGS`, regenerate `experiment_settings.json`:
`python3 -c "import json; from src.evaluation.experiments import ALLOWED_SETTINGS; json.dump(ALLOWED_SETTINGS, open('frontend/src/testing/fixtures/experiment_settings.json','w'))"`.

**Frontend.** Standalone components, signals, no UI kit, design tokens in
`frontend/src/styles.scss`, light and dark themes. Page layout pattern:
- an `h2` with a one- or two-sentence intro;
- a row of stat tiles (`.facts`: `.fact-value`, `.fact-label`, optional
  `.fact-note`; the label renders above the value);
- then tables and charts;
- longer explanations in `<details class="how">`.

Charts use `baseOptions()` from `shared/chart.ts`.

**Help tooltips.** Explain jargon with `<app-hint term="…" />`, with the definition in
`core/glossary.ts` (one definition per term, at most 280 characters, plain
language). Tooltips hold definitions only, never information or actions the page
needs. Put a hint beside a form label, never inside a `<label>` element.

**Writing in the UI and docs.** Use the names in the Glossary above. Plain language for a non-specialist; say what a
number means ("0.5 is a coin flip"). No hype, no promises of returns; the app
must keep saying "Research tool, not financial advice".

**Security.**
- **Workflows:** new workflows start from `permissions: contents: read`, and jobs ask for more only when needed. Pin every action to a commit SHA with the version in a comment (`uses: owner/action@<sha> # v1.2.3`). Use `persist-credentials: false` on checkout unless the job pushes. Never expand `${{ … }}` inside `run:`; pass values through `env:`. `zizmor --offline .github/workflows` must report no findings.
- **Secrets** go in `.env` or Kubernetes Secrets only. The Security workflow scans the history with gitleaks.
- **Inline scripts:** keep CSP-safe. A new inline script in `index.html` is allowed automatically by its hash (`api/security.py`), but nothing may need `unsafe-eval`.

**Size and unused code.** No `.py` or `.ts` file over 500 lines, and no unused
function, method, class or import: `python3 scripts/check_code.py` (CI's Code
job) checks both. Split a file that grows past the limit by responsibility. A
file in its `OVER_LIMIT` list may shrink but not grow; remove the entry once it
is under the limit.

**Terminology.** The Glossary's retired names must not come back: `python3
scripts/check_terms.py` (CI's Code job; stdlib only, under a second) fails on a
retired name in UI strings (`frontend/src/app` `.ts` and `.html`, not specs), in
API field names and routes (`api/`, `src/personal/`, the comparator) and in
Python identifiers (split into words: `top_recommendation`, `ticker`, `ideas`).
It checks only names that mean nothing else; "run", "prediction" and "stock"
also mean an MLflow run, a stored table or a verb, so reviews check those. A
route with `deprecated=True` is exempt by itself. Everything else that is
allowed is in the script's exception lists (`FIELD_EXCEPTIONS`,
`IDENTIFIER_EXCEPTIONS`), each with its reason: stored names (`api/db.py`,
`api/store.py` and the migrations are not scanned), the deprecated API aliases
(remove the entry when its release ends) and yfinance's own `Ticker`. Research
folders, `docs/` and `CHANGELOG.md` are not scanned. Add an exception only with
a reason; otherwise rename.

**Shell.** `shellcheck`-clean. CI checks `run.sh`, `kube.sh`, `scripts/lib/common.sh` and `scripts/check.sh`; add new scripts to that list in `.github/workflows/kubernetes.yml`.

## Workflow

- Every change starts from a GitHub issue, on a branch named `feature/…`,
  `fix/…`, `docs/…` or `chore/…`, with the PR body ending in `Closes #N`.
- **Merging:** `main` is protected and is only changed through squash-merged PRs
  with green checks.
- **Commit messages** start with an imperative verb and say what changes and why.
- **Changelog:** add a line under **Unreleased** in `CHANGELOG.md`.
- **Docs:** update `README.md`, `docs/GUIDE.md`, `docs/ARCHITECTURE.md` and the matching `docs/design/` file when behaviour or structure changes. Keep `ARCHITECTURE.md` at 300 lines or fewer. Record a lasting decision as a short file in `docs/adr/` (context, decision, consequences) and link it from `ARCHITECTURE.md`.
- CI on a PR:
  - **Tests** (Python 3.10/3.12/3.13, a PostgreSQL job, Angular tests and build, the presentation build)
  - **Kubernetes** (helm lint, kubeconform, promtool, then a full k3d deploy: monitoring, scaled mode, GitOps, backup → lose volume → restore). It takes **~45 min**.
  - **Release** (image build and Grype scan)
  - **Security** (gitleaks, pip-audit, npm audit, zizmor) and **Scorecard** (on `main`, weekly)
  - **Daily prediction**, when its script changes.
- In CI logs, look at the failing step's annotations first.
- The user runs `./run.sh` / `./kube.sh` on their own machines after merging,
  and those scripts fetch the latest `main`. Unmerged work does not reach them.

## Presentation

`docs/presentation/Ledger.pptx` explains what the project is, how it works and
what it is for. It is **generated** from `docs/presentation/build.js`
(pptxgenjs), and both files are committed.

**Keep it current.** When a change alters something the deck describes, update
the deck in the same pull request. That includes:
- features or pages;
- how the model works;
- headline results;
- the architecture or stack;
- CI and workflow;
- how to run it;
- limits and next steps.

To update it:
1. Edit the content in `build.js`.
2. Bump `UPDATED`.
3. Rebuild: `cd docs/presentation && npm ci && npm run build`.
4. Check the slides visually (no text overflow or overlap).
5. Commit `build.js` and `Ledger.pptx`.

Never edit the `.pptx` by hand: the next build would overwrite it.

## Definition of done

- [ ] Targeted tests for the change, plus the full Python suite and the frontend tests and build, pass locally.
- [ ] New behaviour has tests, and model changes have both the signal and the no-signal test.
- [ ] Fixtures, `models.ts`, migrations, `ALLOWED_SETTINGS` and the Helm chart are updated where the change touches them.
- [ ] UI changes are checked in a browser at desktop and phone width (390 px) in light and dark mode, with no horizontal page overflow.
- [ ] Docs, `CHANGELOG.md` and, when its content is affected, the presentation (`docs/presentation/`) are updated.
- [ ] When code moves or an entry point is renamed, the Navigation table above is updated.
- [ ] `python3 scripts/check_terms.py` passes (no retired names).

## Known pitfalls

- **Demo vs live.**
  - `run.sh` defaults to demo mode (synthetic prices, `data/demo.db`); `--live` uses Yahoo Finance and `data/predictions.db`.
  - Demo results say nothing about real markets, and the planted reversal makes the model look far better than it will on real data.
  - Demo mode analyses only the first 40 symbols.
- **Live track record needs time.** Runs are scored only after their horizon
  (5 trading days). Repeated runs on the same price date are stored; only the
  latest is scored (`superseded` marks the others).
- **k3d volumes cannot grow.** Keep profile storage sizes equal. Helm 4 needs
  `--force-conflicts` when taking over Flux-managed objects.
- **Generated files.** Never commit `dump.rdb`, databases or anything under `data/`.
  `.gitignore` covers them; check `git status` for stray files before committing.
- **MLflow in CI** runs `mlflow-skinny` against `ghcr.io/mlflow/mlflow:v3.16.1`.
  The server image needs memory, so job execution is turned off there.
- **Changing the default model** (`ml_config.model`) also requires:
  - the ranking weights in `config.yaml` (the default composite is the model alone);
  - the experiment form keys in `frontend/src/app/pages/experiments.ts`.
