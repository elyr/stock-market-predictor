# Epic: Grade B in every area

**Goal:** raise *Maintenance cost* (C+ today) and *Consistent terminology* (C today) to **B**, and keep *Architecture* at **B** while the code is restructured.

**Out of scope:** new features, model or statistics changes, database schema renames, and shrinking the stack (the full MLOps stack is intentional).

**Process:** one GitHub issue per ticket, labelled `epic:grade-b`. Each PR ends with `Closes #N` and adds a line to the CHANGELOG, as `AGENTS.md` requires.

## What "B" means (exit criteria)

| Area | Grade B when |
|---|---|
| Architecture | No Python or TypeScript file is over 500 lines. Each concept lives in exactly one module. Nothing is unused. A CI check enforces all three. |
| Maintenance | `run.sh` and `kube.sh` share their logic, with each setting defined once. A fast test set finishes in under 60 s. `ARCHITECTURE.md` is 300 lines or fewer, `README.md` 150 or fewer. No stale branches. One frontend component layout. |
| Terminology | A glossary in `AGENTS.md`. Each concept has one name in the UI, the API and the code. A CI check rejects the retired names. |

## Phase 1: Quick wins (about 1 week)

| # | Ticket | Area | Size | Acceptance criteria |
|---|---|---|---|---|
| 1 | **Write the glossary** | Terminology | S | `AGENTS.md` gets a "Glossary" section for code and docs, separate from the UI tooltip definitions in `core/glossary.ts`: *Ledger* (the product), *analysis* (one computation over a universe), *forecast* (a predicted range for one horizon), *pick* (a ranked suggestion), *asset* (a stock or crypto; its id is the *symbol*), *universe*, *horizon*. Each entry lists the names it retires. |
| 2 | **One product name: Ledger** | Terminology | S | The log file, logger names, CLI help, README title and Helm/compose labels say *Ledger*. The repo name is mentioned only in install instructions. |
| 3 | **Delete merged branches** | Maintenance | S | About 30 squash-merged remote branches are deleted. "Automatically delete head branches" is turned on in GitHub settings. |
| 4 | **Remove `src/utils/helpers.py`** | Architecture | S | The 2 unused functions are deleted. Each function still in use moves next to its only caller, or into a small module with a clear name. `helpers.py` and `test_helpers.py` are gone. |
| 5 | **Decide on sentiment analysis** | Architecture | S | Either delete `sentiment_analysis.py` and `use_sentiment`, or keep it behind one config flag with a test. Record the decision in a short ADR (ticket 16). |
| 6 | **Fast test set** | Maintenance | M | Model-training tests carry `@pytest.mark.slow`. `pytest -m "not slow"` runs in under 60 s and backs `scripts/check.sh --quick`, replacing its hand-picked file list. CI still runs everything. |

## Phase 2: Structure (about 2–3 weeks)

| # | Ticket | Area | Size | Acceptance criteria |
|---|---|---|---|---|
| 7 | **Split `StockRanker`** | Architecture | L | A small `AnalysisRunner` coordinates, and one module per step does the work (features, the next-week model, the 3-day forecast, the long-term model, volatility). No file over 500 lines. The output of a fixed synthetic universe is unchanged (snapshot test). |
| 8 | **Fold `pipelines.py` into the runner** | Architecture | M | Only one orchestration entry point is left. The CLI, API and daily script all call it. *Depends on 7.* |
| 9 | **Merge the evaluation code** | Architecture | M | `src/models/evaluation.py` and `src/evaluation/` become one `src/evaluation/` package (out-of-sample evidence, comparator, experiments). Imports are updated and the old module is deleted. |
| 10 | **Split `api/service.py` by domain** | Architecture | L | Services for analysis, track record, portfolio, brief and admin, each under 500 lines. `main.py` only wires routes. API tests pass unchanged. |
| 11 | **Slim down `src/cli.py`** | Architecture | M | Commands are thin wrappers over the runner and the services. Under 300 lines. *Depends on 7 and 10.* |
| 12 | **File size and dead code guard** | Architecture | S | CI fails when a `.py` or `.ts` file is over 500 lines (the allowlist must shrink to empty by the end of the epic) and when vulture or ts-prune reports unused code. |

## Phase 3: Naming (about 1–2 weeks, after phase 2 so files move only once)

| # | Ticket | Area | Size | Acceptance criteria |
|---|---|---|---|---|
| 13 | **Apply the glossary to the code** | Terminology | M | `StockRanker` becomes `AssetRanker`, or disappears in ticket 7. Run, prediction and forecast are renamed according to the glossary (`daily_prediction.py` becomes `daily_analysis.py`, and the workflow is renamed too). *ticker* disappears. Database columns keep their names, with a mapping documented in one place. |
| 14 | **Apply the glossary to the UI and API** | Terminology | M | The UI uses *analysis*, *forecast* and *pick* only (no "ideas", "recommendation" or "run"). API fields follow the glossary; old fields stay as deprecated aliases for one release and are listed in the CHANGELOG. |
| 15 | **Merge overlapping pages** | Terminology | M | Updates the presentation in the same PR. Outlook, Forecast, Next 3 days, Long-term and Volatility become a coherent set (suggested: *Outlook* for picks across horizons, with a horizon tab for 3 days, 1 week and 1 month, plus *Forecast* for ranges and volatility). Each route, file name and menu label is identical (`next-days.ts` matches its page). |
| 16 | **Terminology check in CI** | Terminology | S | A script rejects retired names in UI strings, API fields and new code, and is allowed only for documented exceptions. |

## Phase 4: Operations and docs (about 1–2 weeks)

| # | Ticket | Area | Size | Acceptance criteria |
|---|---|---|---|---|
| 17 | **Make the run paths share their logic** | Maintenance | M | The full stack stays, since it is the learning goal. `run.sh` and `kube.sh` remain the only entry points, as thin wrappers around `scripts/lib/common.sh`. `docker-compose.yml` and the Helm chart read one shared set of defaults, so each setting is defined once. The README documents only these two scripts. |
| 18 | **Clarify the store backends** | Maintenance | S | SQLite for local and demo use, Postgres for deployment, documented in one table. The queue runs on the same backend, so there's no extra service. |
| 19 | **Rewrite `ARCHITECTURE.md`** | Maintenance | M | 300 lines or fewer: one diagram, the module map and the key decisions. Long rationale moves to `docs/adr/` (one short file per decision, including tickets 5, 15 and 17). |
| 20 | **Shorten the README** | Maintenance | S | 150 lines or fewer: what Ledger is, quick start, the daily routine and links to the docs. |
| 21 | **One frontend component layout** | Maintenance | M | Every page uses one convention (suggested: separate `.html` and `.scss` files once a template is over 40 lines). `AGENTS.md` documents it, and a lint rule enforces it. |

## Order and dependencies

```
Phase 1 (1-6, in parallel)
   └─> Phase 2: 7 ─> 8 ─> 11
                9, 10 (in parallel with 7) ─> 12
          └─> Phase 3: 13 ─> 14 ─> 15 ─> 16
Phase 4 (17-21) can start after phase 1, in parallel with phases 2 and 3
```

**Estimate:** 21 tickets, about 5–8 weeks part-time. Grades should be reached at: Terminology B after phase 3, Maintenance B after phases 1 and 4, Architecture held at B (and on its way to A) after phase 2.

## Risks

- **The refactor changes the numbers.** Lock outputs with snapshot tests on the synthetic universe before tickets 7–10.
- **The renames break the frontend or saved data.** Keep deprecated API aliases for one release, and don't rename database columns.
- **The big-bang branch problem.** One PR per ticket, each merged to `main` behind passing CI.
