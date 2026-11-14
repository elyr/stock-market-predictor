# Reference: configuration, testing, limitations, extension points

Part of the [architecture](../ARCHITECTURE.md); section numbers (§) are unchanged and indexed in the architecture.

## 15. Configuration reference

All settings are in `config/config.yaml`.

| Section | Key | Default | Effect |
|---|---|---|---|
| `universes.{stocks,crypto}` | `symbols` | see file | the universe |
| | `timeframe` | `2y` | history fetched |
| | `periods_per_year` | 252 / 365 | annualisation |
| | `filters` | see §4 | price, volume, market cap |
| | `portfolio.max_per_sector` | 3 / 0 | sector cap (0 = none) |
| | `portfolio.weighting` | `inverse_volatility` | or `equal` |
| `technical_analysis.indicators` | `rsi`, `macd`, … | standard | indicator periods |
| `ml_config.models` | `random_forest`, `xgboost`, `neural_network`, `lstm` | see file | hyperparameters; `enabled: false` disables |
| `ml_config.training` | `target` | `relative` | or `absolute` |
| | `horizon` | 5 | days ahead |
| | `test_size` | 0.2 | hold-out share of dates |
| | `calibrate` | true | Platt calibration on the hold-out |
| | `cross_validate`, `cv_splits` | true, 3 | time-series CV with purge gap |
| `volatility` | `enabled`, `horizon` | true, 5 | volatility model |
| `ranking_config` | `weights`, `top_picks` | see §7, 10 | composite weights, portfolio size |
| `backtest` | `period`, `test_days`, `retrain_every`, `min_train_days`, `cost_bps` | 2y, 120, 20, 120, 5 | backtest defaults |
| `tracking` | `database` | `data/predictions.db` | SQLite file |
| `scheduler` | `enabled`, `time`, `universes` | false, 22:30, both | daily automatic analysis in the API |
| `signals` | `schedule.open`, `schedule.close`, `stocks_weekdays_only` | 09:45, 16:15 New York, true | alert scans |
| | `thresholds`, `cooldown_hours`, `history_days` | see §11a, 12, 60 | alert sensitivity |
| `experiments` | `test_days`, `lockbox_days` | 250, 60 | development and locked periods |
| `api_config` | `rate_limits`, `retry_attempts` | 7,200/h, 3 | Yahoo Finance behaviour |

---

## 16. Testing strategy

| Suite | Runs | Covers |
|---|---|---|
| `tests/` (pytest) | offline, ~2 min | data, indicators, models, both pipelines, portfolio, backtest, API |
| `frontend/` (Vitest + jsdom) | offline, seconds | formatting, evidence meter, every page for both dashboards (including Alerts, Predicted vs actual and Experiments), rendered from real API responses captured in demo mode |

Key checks:

- **No lookahead, twice over.** (1) Scrambling every price after a cutoff
  leaves every pick decided before the cutoff unchanged, with and without the
  model. (2) On data with no signal no strategy shows significant edge, while on
  data with a planted signal the model finds it (IC t > 3).
- **Methodology.** Purge gap size; relative targets sum to zero across the
  universe; calibration does not worsen the Brier score; SHAP contributions plus
  the bias equal the model's output; the volatility model beats the naive
  forecast on clustered data; RSI matches the published Wilder example.
- **Separation.** Stock and crypto pipelines have distinct models, model files,
  calendars and symbols; the crypto dashboard renders only crypto.
- **Alerts.** Planted crashes, volume spikes and gaps are caught; a quiet day
  raises nothing; a market-wide drop raises one alert; dedupe, cooldown and
  escalation; channel failures do not block others; schedule across weekends
  and the clock change.
- **Comparator and experiments.** Skilled scores make a staircase and unskilled
  ones show no edge; experiment windows are identical across horizons and never
  overlap the locked period; settings validation; a locked check runs once.
- **API.** Full job lifecycle, deduplication, outcome scoring against known
  prices, simulated runs never replacing live ones, validation errors.

CI (`.github/workflows/tests.yml`) runs the Python suite on 3.10, 3.12 and 3.13
and the frontend tests and production build on Node 22.


---

## 18. Known limitations

- **Survivorship bias.** Universes are today's large assets; backtests over past
  years exclude those that fell away, which flatters results.
- **Free data.** No fundamentals, estimates, options or order-book data; those
  are where most real edge comes from.
- **Execution.** Close-to-close fills with a fixed cost; no spread, impact or
  borrow costs.
- **`yfinance` is unofficial**; Yahoo may throttle or change it. Coinbase covers
  crypto when it does; for stocks the free Alpha Vantage tier covers only a few
  symbols a day.
- **Demo numbers are synthetic** and say nothing about real markets.

---

## 19. Extension points

- **New asset class:** subclass `AssetRanker` in `pipelines.py`, add
  `add_universe_features` and `asset_metadata`, register it in `PIPELINES`, and
  add a `universes` entry in the config. The API, backtest and frontend pick it
  up by key (add a navigation entry in `app.ts` and routes in `app.routes.ts`).
- **New data source:** implement the `DataCollector` methods used by the
  pipeline (see `SyntheticDataCollector`) and pass it to `create_pipeline`.
- **New feature:** compute it in the preprocessor, indicators or
  `add_universe_features`; if scale-free it becomes a model input automatically.
  Add a readable name to `FEATURE_LABELS` for explanations.
- **New model:** add a trainer and config block in `ReturnPredictor`; any
  classifier with `predict_proba` joins the ensemble and calibration.
