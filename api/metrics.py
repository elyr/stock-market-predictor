"""
Prometheus metrics, served at ``/metrics``.

Three kinds:

- **Service**: HTTP requests and latency per route, background jobs by kind and
  outcome, job durations, when each kind of job last succeeded.
- **Data**: how old the newest prices in the latest analysis are.
- **Model**: the latest analysis's out-of-sample rank IC and t-statistic, the
  rank IC of recent live predictions once their outcome is known, and the
  registry's champion version.

Data and model values are read from the database when Prometheus scrapes, so
they are correct right after a restart. Counters and job timestamps start
from zero with each process, as usual for Prometheus.
"""

import logging
import time
from datetime import date
from typing import Callable, Dict, Iterable, Optional

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

logger = logging.getLogger(__name__)

# Live runs used for the rolling rank IC (about three weeks of daily analyses)
LIVE_IC_WINDOW = 15

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
JOB_BUCKETS = (1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600)


class Metrics:
    """All metrics of one app instance, on their own registry (so tests can create several apps)."""

    def __init__(self):
        self.registry = CollectorRegistry()
        self.requests = Counter('ledger_http_requests', 'HTTP requests', ['method', 'route', 'status'],
                                registry=self.registry)
        self.latency = Histogram('ledger_http_request_duration_seconds', 'HTTP request duration',
                                 ['method', 'route'], buckets=LATENCY_BUCKETS, registry=self.registry)
        self.jobs = Counter('ledger_jobs', 'Background jobs finished', ['kind', 'universe', 'status'],
                            registry=self.registry)
        self.job_duration = Histogram('ledger_job_duration_seconds', 'Background job duration',
                                      ['kind', 'universe'], buckets=JOB_BUCKETS, registry=self.registry)
        self.jobs_running = Gauge('ledger_jobs_running', 'Background jobs running now', ['kind', 'universe'],
                                  registry=self.registry)
        self.last_success = Gauge('ledger_job_last_success_timestamp_seconds',
                                  'When a job of this kind last succeeded (Unix time)', ['kind', 'universe'],
                                  registry=self.registry)
        self.alerts = Counter('ledger_alerts_published', 'Alerts published in the app', ['universe', 'type'],
                              registry=self.registry)
        self.info = Gauge('ledger_info', 'Static information about this instance', ['version', 'mode'],
                          registry=self.registry)

    # ------------------------------------------------------------- recording

    def job_started(self, kind: str, universe: str) -> None:
        self.jobs_running.labels(kind, universe).inc()

    def job_finished(self, kind: str, universe: str, status: str, seconds: float) -> None:
        self.jobs_running.labels(kind, universe).dec()
        self.jobs.labels(kind, universe, status).inc()
        self.job_duration.labels(kind, universe).observe(seconds)
        if status == 'succeeded':
            self.last_success.labels(kind, universe).set(time.time())

    def alerts_published(self, universe: str, alerts: Iterable[Dict]) -> None:
        for alert in alerts:
            self.alerts.labels(universe, alert.get('type', 'unknown')).inc()

    def watch_state(self, universes: Iterable[str], store, registry_for: Callable[[str], Optional[object]]) -> None:
        """Report data and model values from the database at every scrape."""
        self.registry.register(StateCollector(list(universes), store, registry_for))


class StateCollector(Collector):
    """Values derived from stored runs and the model registry, computed at scrape time."""

    def __init__(self, universes, store, registry_for):
        self.universes = universes
        self.store = store
        self.registry_for = registry_for

    def describe(self):
        return []  # values are computed at collection time; nothing to check at registration

    def collect(self):
        data_age = GaugeMetricFamily('ledger_data_age_days',
                                     'Days between today and the newest prices in the latest analysis',
                                     labels=['universe'])
        last_run = GaugeMetricFamily('ledger_last_analysis_timestamp_seconds',
                                     'When the latest analysis was stored (Unix time)', labels=['universe'])
        ic = GaugeMetricFamily('ledger_model_rank_ic', 'Out-of-sample rank IC of the latest analysis\'s model',
                               labels=['universe'])
        ic_t = GaugeMetricFamily('ledger_model_rank_ic_t_stat', 't-statistic of that rank IC', labels=['universe'])
        live_ic = GaugeMetricFamily('ledger_live_rank_ic',
                                    f'Average rank IC of the last {LIVE_IC_WINDOW} scored live analyses',
                                    labels=['universe'])
        live_runs = GaugeMetricFamily('ledger_live_scored_runs', 'Live analyses scored against outcomes',
                                      labels=['universe'])
        forecast_coverage = GaugeMetricFamily(
            'ledger_forecast_coverage', 'Share of scored live price ranges that contained the outcome',
            labels=['universe', 'horizon', 'level'])
        forecast_scored = GaugeMetricFamily('ledger_forecast_scored', 'Live price ranges scored against outcomes',
                                            labels=['universe', 'horizon'])
        version = GaugeMetricFamily('ledger_model_champion_version', 'Champion version in the model registry',
                                    labels=['universe'])
        pinned = GaugeMetricFamily('ledger_model_pinned', '1 when analyses use a pinned model', labels=['universe'])

        for universe in self.universes:
            try:
                run = self.store.latest_run(universe)
                if run:
                    data_age.add_metric([universe], (date.today() - date.fromisoformat(run['data_date'][:10])).days)
                    last_run.add_metric([universe], _timestamp(run['created_at']))
                    quality = (run.get('summary') or {}).get('model_quality') or {}
                    if _number(quality.get('ic_mean')) is not None:
                        ic.add_metric([universe], quality['ic_mean'])
                    if _number(quality.get('ic_t_stat')) is not None:
                        ic_t.add_metric([universe], quality['ic_t_stat'])
                scored = [r for r in self.store.list_runs(universe, limit=500)
                          if not r['simulated'] and r['evaluated_at']]
                live_runs.add_metric([universe], len(scored))
                recent = [r['rank_ic'] for r in sorted(scored, key=lambda r: r['data_date'])[-LIVE_IC_WINDOW:]
                          if r['rank_ic'] is not None]
                if recent:
                    live_ic.add_metric([universe], sum(recent) / len(recent))
            except Exception as e:  # a scrape must never fail because of one value
                logger.warning(f'Metrics for {universe}: {e}')
            try:
                from src.models.forecast import reliability
                scored = self.store.scored_forecasts(universe, simulated=False)
                for horizon in sorted({r['horizon'] for r in scored}):
                    stats = reliability([r for r in scored if r['horizon'] == horizon])
                    forecast_scored.add_metric([universe, horizon], stats['scored'])
                    forecast_coverage.add_metric([universe, horizon, '50'], stats['coverage_50'])
                    forecast_coverage.add_metric([universe, horizon, '90'], stats['coverage_90'])
            except Exception as e:
                logger.warning(f'Forecast metrics for {universe}: {e}')
            registry = self.registry_for(universe)
            if registry is not None:
                try:
                    champion = registry.champion(universe)
                    if champion is not None:
                        version.add_metric([universe], float(champion))
                    pinned.add_metric([universe], 1.0 if registry.pinned(universe) else 0.0)
                except Exception as e:
                    logger.warning(f'Registry metrics for {universe}: {e}')
        yield from (data_age, last_run, ic, ic_t, live_ic, live_runs, version, pinned, forecast_coverage,
                    forecast_scored)


def _number(value) -> Optional[float]:
    if isinstance(value, (int, float)) and value == value:
        return float(value)
    return None


def _timestamp(iso: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(iso).timestamp()
