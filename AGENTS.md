# AGENTS.md

Instructions for AI coding agents (and a fast orientation for people) working on
**Ledger**. `CLAUDE.md` and `.github/copilot-instructions.md` point here, so this
file is the one to keep up to date.

Ledger ranks US stocks and crypto by how likely each is to beat the rest of its
universe over the next few days, and shows honestly how much evidence there is
for that: out-of-sample rank IC with t-statistics, backtests, a live track
record, price ranges and volatility forecasts. It is also a learning vehicle for
an end-to-end MLOps stack (FastAPI, Angular, PostgreSQL, Redis/RQ, MLflow,
Prometheus/Grafana, Helm, k3d, Flux, GHCR). Read `docs/ARCHITECTURE.md` before
any non-trivial change; it is accurate and is the design reference.

## Map

| Path | What lives there |
|---|---|
| `src/data/` | Yahoo Finance collector, cleaning and features (`preprocessor.py`), synthetic market for demo and tests (`synthetic.py`) |
| `src/models/cross_section.py` | **The return model**: residual returns, ten ranked `XS_*` features, `Target_XS`, ridge (+ optional XGBoost), calibration |
| `src/models/ml_models.py` | Purged split, IC, reliability table; the `legacy` classifier ensemble |
| `src/models/volatility.py`, `forecast.py` | Volatility model; price ranges (split-conformal) for the Forecast page |
| `src/prediction/` | `StockRanker` (shared pipeline), `StockPipeline` / `CryptoPipeline`, portfolio rules |
| `src/backtest/`, `src/evaluation/` | Walk-forward backtester; predicted-vs-actual report; experiments and the lockbox |
| `api/` | FastAPI app (`main.py`), per-universe service (`service.py`), store and SQLAlchemy tables (`store.py`, `db.py`), Alembic migrations, jobs (in-process or RQ), Prometheus metrics |
| `frontend/src/app/` | Angular 22: `pages/` (one per menu entry), `shared/` (chart, hint, evidence meter, score bar), `core/` (API client, stores, types, `format.ts`, `glossary.ts`) |
| `config/config.yaml` | Universes, model, ranking weights, backtest, experiments, signals, scheduler |
| `deploy/helm/ledger`, `deploy/gitops` | Helm chart (with Prometheus alert rules in `files/`), Flux manifests |
| `run.sh`, `kube.sh` | One-command local run (venv or Docker) and k3d deployment; both fetch the latest `main` |
| `tests/` | pytest suite (offline); `tests/prometheus/` holds promtool tests for the alert rules |
| `docs/presentation/` | The project presentation: `build.js` generates `Ledger.pptx` (see Presentation below) |

## Commands

Run from the repository root. Times are on a typical laptop.

```bash
pip install -r requirements.txt                 # Python 3.10–3.13
python3 -m pytest -q                            # full suite, ~8–10 min (slow: trains models)
python3 -m pytest -q tests/test_cross_section.py tests/test_forecast.py   # targeted, ~1 min
TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres python3 -m pytest -q tests/test_store_backends.py
                                                # store tests also on PostgreSQL (CI does this)
cd frontend && npm ci && npx ng test --watch=false && npx ng build   # ~10 s tests, ~15 s build
scripts/check.sh --quick                        # targeted Python tests + frontend tests and build
scripts/check.sh                                # everything CI runs that works without a cluster
DEMO_MODE=true uvicorn api.main:app --port 8000 # demo server: synthetic prices, seeds both dashboards (~2 min)
```

The full Python suite is slow; run it in the background or run the tests for the
area you touched first, then the full suite once before opening the PR.

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

**Writing in the UI and docs.** Plain language for a non-specialist; say what a
number means ("0.5 is a coin flip"). No hype, no promises of returns; the app
must keep saying "Research tool, not financial advice".

**Shell.** `shellcheck`-clean. CI checks `run.sh`, `kube.sh`, `scripts/lib/common.sh` and `scripts/check.sh`; add new scripts to that list in `.github/workflows/kubernetes.yml`.

## Workflow

- Every change starts from a GitHub issue, on a branch named `feature/…`,
  `fix/…`, `docs/…` or `chore/…`, with the PR body ending in `Closes #N`.
- **Merging:** `main` is protected and is only changed through squash-merged PRs
  with green checks.
- **Commit messages** start with an imperative verb and say what changes and why.
- **Changelog:** add a line under **Unreleased** in `CHANGELOG.md`.
- **Docs:** update `README.md` / `docs/ARCHITECTURE.md` when behaviour or structure changes.
- CI on a PR:
  - **Tests** (Python 3.10/3.12/3.13, a PostgreSQL job, Angular tests and build, the presentation build)
  - **Kubernetes** (helm lint, kubeconform, promtool, then a full k3d deploy: monitoring, scaled mode, GitOps, backup → lose volume → restore). It takes **~45 min**.
  - **Release** (image build and Grype scan)
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

## Known pitfalls

- **Demo vs live.**
  - `run.sh` defaults to demo mode (synthetic prices, `data/demo.db`); `--live` uses Yahoo Finance and `data/predictions.db`.
  - Demo results say nothing about real markets, and the planted reversal makes the model look far better than it will on real data.
  - Demo mode analyses only the first 40 symbols.
- **Live track record needs time.** Runs are scored only after their horizon
  (5 trading days). Repeated runs on the same price date are stored separately.
- **k3d volumes cannot grow.** Keep profile storage sizes equal. Helm 4 needs
  `--force-conflicts` when taking over Flux-managed objects.
- **Generated files.** Never commit `dump.rdb`, databases or anything under `data/`.
  `.gitignore` covers them; check `git status` for stray files before committing.
- **MLflow in CI** runs `mlflow-skinny` against `ghcr.io/mlflow/mlflow:v3.16.1`.
  The server image needs memory, so job execution is turned off there.
- **Changing the default model** (`ml_config.model`) also requires:
  - the ranking weights in `config.yaml` (the default composite is the model alone);
  - the experiment form keys in `frontend/src/app/pages/experiments.ts`.
