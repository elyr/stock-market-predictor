# API and frontend

Routes, response shapes and the Angular app. Part of the [architecture](../ARCHITECTURE.md); section numbers (§) are unchanged and indexed in the architecture.

## 12. API

Interactive documentation is served at `/api/docs`. Every asset-class endpoint
takes `{universe}` = `stocks` or `crypto`.

**Security headers** (`api/security.py`) are on every response: `nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a restrictive
`Permissions-Policy` and `Cross-Origin-Opener-Policy`.

The web app also gets a Content Security Policy:
- scripts come only from the app, plus the built `index.html`'s inline script, allowed by its SHA-256 computed at start-up;
- no framing, no plugins, requests only to the same server.

`/api/docs` is left without the policy because Swagger UI loads from a CDN.
See also [SECURITY.md](../../SECURITY.md).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | status, version, demo flag |
| GET | `/api/universes` | both universes' settings |
| GET | `/api/{universe}` | one universe's settings and last run time |
| POST | `/api/{universe}/analysis` | start an analysis job (`top_n`, `symbols` optional) |
| GET | `/api/{universe}/analysis/latest` | latest live run: summary, model quality, calibration, picks, ranking |
| GET | `/api/{universe}/analyses`, `/analyses/{id}` | analysis history and detail with outcomes (`/runs` and `/runs/{id}` are deprecated aliases) |
| GET | `/api/{universe}/assets/{symbol}` | 250 days of price and indicators, latest standing, reasons |
| GET | `/api/{universe}/volatility` | volatility model skill and per-asset forecasts |
| GET | `/api/{universe}/market` | benchmark moves for the header |
| GET | `/api/{universe}/track-record` | live and simulated summaries, curves, runs |
| POST | `/api/{universe}/track-record/evaluate` | score matured runs now |
| POST | `/api/{universe}/backtests` | start a backtest job (`top_n`, `test_days`, `retrain_every`, `cost_bps`, `use_ml`) |
| GET | `/api/{universe}/backtests`, `/backtests/{id}` | saved backtests and full results |
| GET | `/api/jobs`, `/api/jobs/{id}` | job status for polling |
| GET | `/api/notifications?universe=&unread_only=` | alerts, newest first |
| GET | `/api/notifications/unread` | unread counts per universe and severity |
| POST | `/api/notifications/{id}/read`, `/api/notifications/read-all?universe=` | mark as read |
| POST | `/api/{universe}/signals/scan` | scan now (`session`: `open` or `close`) |
| GET | `/api/{universe}/trend` | the trend rule's record in this universe, whether it passes the accuracy bar and why, and each asset's state with the date it last changed |
| GET | `/api/signals/schedule` | scan times and the next runs |
| GET | `/api/{universe}/performance?source=&backtest_id=` | predicted-vs-actual report (live or a backtest) |
| GET | `/api/{universe}/performance/scores.csv` | full score log as CSV (`predictions.csv` is a deprecated alias) |
| GET | `/api/{universe}/long-term` | the long-term ranking (about a month ahead) with its evidence and learned weights |
| GET | `/api/{universe}/brief`, `/brief.md` | the weekly brief (JSON or Markdown) |
| GET | `/api/{universe}/portfolio` | your holdings, gains, history against the benchmark, risk and warnings |
| POST | `/api/{universe}/portfolio/transactions` | record a buy or a sale (`symbol`, `side`, `trade_date`, `quantity`, `price`, `fees`, `note`) |
| DELETE | `/api/{universe}/portfolio/transactions/{id}` | remove a trade (refused when a later sale depends on it) |
| GET | `/api/{universe}/portfolio/transactions.csv` | every trade as CSV |
| GET | `/api/experiments/settings` | settings an experiment may change, with ranges |
| GET/POST | `/api/{universe}/experiments` | list, or start an experiment (`name`, `settings`, `top_n`) |
| GET | `/api/{universe}/experiments/{id}` | one experiment with development and locked results |
| POST | `/api/{universe}/experiments/{id}/lockbox` | check on the locked period (once) |

Server settings come from environment variables (`api/settings.py`):
`CONFIG_PATH`, `DEMO_MODE`, `DATABASE_PATH`, `FRONTEND_DIST`, `CORS_ORIGINS`,
`SEED_DEMO`.

---

## 13. Frontend

Angular 22, standalone components, signals for state, lazy-loaded pages,
Chart.js for charts, no UI kit.

```
frontend/src/app/
├── app.ts / app.html            Shell: navigation rail with both dashboards, pages grouped by purpose
├── app.routes.ts                /stocks/... and /crypto/... share one set of page routes
├── core/
│   ├── api.service.ts           Typed HTTP client, job polling
│   ├── universe-store.ts        One signal store per dashboard (no shared state)
│   ├── models.ts                API response types
│   ├── format.ts                Number formatting, t-statistic → plain verdict
│   ├── glossary.ts              Every help definition, in one place
│   └── route-universe.ts        Which dashboard a route belongs to
├── shared/
│   ├── evidence-meter.ts        Out-of-sample IC on a scale with the luck band shaded
│   ├── chart.ts                 Chart.js wrapper, theme-aware colours, shared chart styling
│   ├── hint.ts                  Accessible "?" help tooltip
│   └── score-bar.ts
└── pages/
    ├── universe-layout.ts       Dashboard header, benchmarks, run button, accent colour
    ├── outlook.*                At-a-glance tiles, evidence, portfolio with reasons, full ranking, model facts, calibration
    ├── forecast.ts              Price ranges for the next day and week, and how often they held
    ├── models.ts                Model registry: versions, champion, pin and roll back
    ├── backtest.ts/html         Settings, verdict, equity curves, metrics, IC, recent picks
    ├── track-record.ts          Live vs simulated record
    ├── volatility.ts            Forecasts vs current volatility
    ├── alerts.ts                Alerts by day, severity, unread filter, check now
    ├── performance.*            Predicted vs actual: deciles, components, IC over time, calibration, breakdowns, log
    ├── experiments.*            Experiment form, comparison with the baseline, locked-period checks
    └── asset.ts                 Price with band, RSI, standing, reasons
```

**Two dashboards.** `/stocks` and `/crypto` render the same page components,
but each gets its own `UniverseStore`, its own API namespace and its own accent
colour (cobalt for stocks, violet for crypto), so they read as separate products
that share a design language.

**Design.** Graph-paper neutrals and slate ink; green and crimson are reserved
for outperformance and underperformance. Public Sans (self-hosted) with tabular
figures. The evidence meter leads each dashboard so the strength of the evidence
is the first thing a reader sees.

**Navigation** groups the pages by the question they answer: *Today* (Outlook,
Forecast, Volatility, Alerts), *Is it working?* (Track record, Backtest,
Predicted vs actual) and *Improve it* (Experiments, Models).

**Stat tiles.** Pages lead with a row of key figures (`.facts`): a label, the
number, and a short note. Longer explanations sit in collapsed "How it works"
sections, so a page can be read at a glance and studied when needed.

**Help hints.** Terms that need explaining (rank IC, t-statistic, Sharpe,
coverage, lockbox…) carry a small "?" button (`app-hint`) whose definition comes
from `core/glossary.ts`, so each term is explained the same way everywhere. It
follows WCAG 2.2 SC 1.4.13 and the usual tooltip guidance:
- it opens on hover after a short delay, on keyboard focus and on tap;
- it stays open while hovered;
- Escape, a click elsewhere or scrolling closes it;
- `aria-describedby` links it, it has a 24 px target, and only one is open at a time;
- it holds short definitions only, never information or actions a page needs.

Hints sit beside a label, not inside it, so they do not change form fields'
accessible names.

**Charts** share one style (`baseOptions`): 2 px lines with no dots until
hovered, bars at most 24 px wide with rounded ends, solid hairline gridlines,
and one tooltip listing every series at the hovered date. Light and dark themes follow the system
setting; keyboard focus is visible; motion is limited to a loading spinner and
respects reduced-motion settings.

In development `ng serve` proxies `/api` to `http://127.0.0.1:8000`
(`proxy.conf.json`). In production the FastAPI server serves the built files and
falls back to `index.html` for client-side routes.
