"""
FastAPI application.

Run in development:      uvicorn api.main:app --reload
Run the demo:            DEMO_MODE=true uvicorn api.main:app
Interactive API docs:    http://127.0.0.1:8000/api/docs

All asset-class endpoints are namespaced by universe: ``/api/stocks/...`` and
``/api/crypto/...``. Long-running work (analysis, backtests) is started with a
POST that returns a job, which the client polls at ``/api/jobs/{id}``.
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from api.jobs import JobManager
from api.logging_setup import configure_logging
from api.metrics import Metrics
from api.notifications import Notifier, next_scan, scan_times
from api.service import UniverseService
from api.settings import Settings, registry_settings
from api.store import NotificationStore, Store
from src.data.collector import load_config
from src.prediction import UNIVERSES
from src.signals import merge_signal_config
from src.evaluation import ALLOWED_SETTINGS

logger = logging.getLogger(__name__)
VERSION = '2.0.0'


class AnalysisRequest(BaseModel):
    top_n: Optional[int] = Field(None, ge=1, le=50, description='Number of picks (default from config)')
    symbols: Optional[List[str]] = Field(None, description='Override the universe symbol list')


class BacktestRequest(BaseModel):
    top_n: Optional[int] = Field(None, ge=1, le=50)
    test_days: Optional[int] = Field(None, ge=20, le=1000, description='Days to simulate')
    retrain_every: Optional[int] = Field(None, ge=5, le=250)
    cost_bps: Optional[float] = Field(None, ge=0, le=200)
    use_ml: bool = True
    symbols: Optional[List[str]] = None


class ExperimentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    settings: Dict[str, object] = Field(default_factory=dict,
                                        description='Setting changes; keys from /api/experiments/settings')
    top_n: Optional[int] = Field(None, ge=1, le=50)


class PromoteRequest(BaseModel):
    pin: bool = Field(True, description='Use this version for analyses without retraining, until unpinned')


class ScanRequest(BaseModel):
    session: str = Field('close', pattern='^(open|close)$',
                         description="'open' checks gaps and early moves; 'close' checks everything")


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings.database_path)
        self.notifications = NotificationStore(self.store)
        self.signal_config = merge_signal_config(load_config(settings.config_path).get('signals'))
        # In-app only for now: every notification is stored and shown in the web app.
        # Extra channels (Telegram, email, ...) can be passed here later.
        self.notifier = Notifier(self.notifications, channels=[],
                                 cooldown_hours=self.signal_config['cooldown_hours'])
        self.metrics = Metrics()
        self.metrics.info.labels(VERSION, 'demo' if settings.demo_mode else 'live').set(1)
        self.jobs = JobManager(max_workers=2, metrics=self.metrics)
        self.services: Dict[str, UniverseService] = {}
        self.registry = create_registry(settings)
        self.metrics.watch_state(UNIVERSES, self.store, lambda universe: self.registry)

    def service(self, universe: str) -> UniverseService:
        if universe not in UNIVERSES:
            raise HTTPException(404, f"Unknown universe '{universe}'")
        if universe not in self.services:
            self.services[universe] = UniverseService(universe, self.settings, self.store,
                                                      notifier=self.notifier, registry=self.registry,
                                                      metrics=self.metrics)
        return self.services[universe]


def _registry_call(action):
    """Run a registry change, turning its errors into HTTP responses."""
    try:
        return action()
    except RuntimeError as e:  # registry turned off
        raise HTTPException(409, str(e))
    except Exception as e:
        if type(e).__name__ == 'MlflowException':
            if 'RESOURCE_DOES_NOT_EXIST' in str(getattr(e, 'error_code', '')) or 'not found' in str(e).lower():
                raise HTTPException(404, 'No such model version')
            raise HTTPException(502, f'Model registry error: {e}')
        raise


def create_registry(settings: Settings):
    """The MLflow model registry, or None when MODEL_REGISTRY=off."""
    if settings.model_registry == 'off':
        return None
    from src.models.registry import ModelRegistry

    uri, artifact_root = settings.mlflow_tracking_uri, settings.mlflow_artifact_root
    if not uri:
        defaults = registry_settings(settings.database_path)
        uri, artifact_root = defaults['mlflow_tracking_uri'], defaults['mlflow_artifact_root']
    return ModelRegistry(uri, artifact_root=artifact_root or None, demo=settings.demo_mode,
                         ui_url=settings.mlflow_ui_url or None)


def due_scans(schedule: Dict, now: datetime) -> List[tuple]:
    """The next scan moment and every (universe, session) due at it."""
    upcoming = []
    for universe in UNIVERSES:
        found = next_scan(schedule, universe, now)
        if found:
            upcoming.append((found[0], found[1], universe))
    if not upcoming:
        return []
    first = min(when for when, _, _ in upcoming)
    return [item for item in upcoming if item[0] == first]


async def signal_scheduler_loop(state: AppState) -> None:
    """Scan both universes twice a day: after the US open and after the close."""
    schedule = state.signal_config['schedule']
    while True:
        due = due_scans(schedule, datetime.now().astimezone())
        if not due:
            return
        await asyncio.sleep(max(1.0, (due[0][0] - datetime.now().astimezone()).total_seconds()))
        for _, session, universe in due:
            service = state.service(universe)
            state.jobs.submit('scan', universe, lambda job, s=service, ss=session: s.scan_signals(job, ss),
                              dedupe=False)
            logger.info(f"Scheduled {session} scan started for {universe}")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.log_format:
        configure_logging(settings.log_format, settings.log_level)
    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = []
        if settings.demo_mode and settings.seed_demo:
            for universe in UNIVERSES:
                if not state.store.has_runs(universe):
                    service = state.service(universe)
                    state.jobs.submit('seed', universe, lambda job, s=service: s.seed_demo(job))
        # With INTERNAL_SCHEDULER=false an outside scheduler (Kubernetes CronJobs) triggers these instead
        if settings.internal_scheduler:
            if state.service('stocks').pipeline.config.get('scheduler', {}).get('enabled'):
                tasks.append(asyncio.create_task(scheduler_loop(state)))
            if state.signal_config.get('enabled', True):
                tasks.append(asyncio.create_task(signal_scheduler_loop(state)))
        yield
        for task in tasks:
            task.cancel()
        state.jobs.shutdown()

    app = FastAPI(title='Market Prediction API', version=VERSION, lifespan=lifespan,
                  docs_url='/api/docs', openapi_url='/api/openapi.json', redoc_url=None,
                  description='Rankings, forecasts, backtests and track record for US stocks and crypto. '
                              'Educational use only; not financial advice.')
    app.state.app_state = state
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=['*'],
                       allow_headers=['*'])

    @app.middleware('http')
    async def record_request(request: Request, call_next):
        """Count requests and their latency per route template (not per URL, to keep labels few)."""
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get('route')
            template = getattr(route, 'path', None) or 'unmatched'
            if template == '/{path:path}':
                template = '/ (web app)'
            state.metrics.requests.labels(request.method, template, str(status)).inc()
            state.metrics.latency.labels(request.method, template).observe(time.perf_counter() - started)

    @app.get('/metrics', include_in_schema=False)
    def metrics():
        """Prometheus metrics (see api/metrics.py)."""
        return Response(generate_latest(state.metrics.registry), media_type=CONTENT_TYPE_LATEST)

    def get_state() -> AppState:
        return state

    def universe_service(universe: str = Path(..., description="'stocks' or 'crypto'"),
                         st: AppState = Depends(get_state)) -> UniverseService:
        return st.service(universe)

    api = APIRouter(prefix='/api')

    @api.get('/health', tags=['meta'])
    def health():
        """Liveness: the process is up and answering."""
        return {'status': 'ok', 'version': VERSION, 'demo': settings.demo_mode}

    @api.get('/ready', tags=['meta'])
    def ready(st: AppState = Depends(get_state)):
        """Readiness: the database can be read and the configuration loaded, so requests can be served."""
        problems = []
        try:
            st.store.has_runs('stocks')
        except Exception as e:  # reported to the probe, not raised
            problems.append(f'database: {e}')
        if not st.signal_config:
            problems.append('configuration not loaded')
        if problems:
            return JSONResponse({'status': 'not ready', 'problems': problems}, status_code=503)
        return {'status': 'ready', 'internal_scheduler': settings.internal_scheduler}

    @api.get('/universes', tags=['meta'])
    def universes(st: AppState = Depends(get_state)):
        return [st.service(u).describe() for u in UNIVERSES]

    @api.get('/jobs', tags=['jobs'])
    def list_jobs(universe: Optional[str] = None, st: AppState = Depends(get_state)):
        return [j.to_dict() for j in st.jobs.list(universe)][:50]

    @api.get('/jobs/{job_id}', tags=['jobs'])
    def get_job(job_id: str, st: AppState = Depends(get_state)):
        job = st.jobs.get(job_id)
        if not job:
            raise HTTPException(404, 'Job not found')
        return job.to_dict()

    @api.get('/notifications', tags=['alerts'])
    def list_notifications(universe: Optional[str] = None, unread_only: bool = False, limit: int = 100,
                           st: AppState = Depends(get_state)):
        if universe and universe not in UNIVERSES:
            raise HTTPException(404, f"Unknown universe '{universe}'")
        return st.notifications.list(universe, unread_only=unread_only, limit=min(max(limit, 1), 500))

    @api.get('/notifications/unread', tags=['alerts'])
    def unread_counts(st: AppState = Depends(get_state)):
        counts = st.notifications.unread_counts()
        empty = {'total': 0, 'critical': 0, 'warning': 0, 'info': 0}
        return {u: counts.get(u, dict(empty)) for u in UNIVERSES}

    @api.post('/notifications/read-all', tags=['alerts'])
    def read_all(universe: Optional[str] = None, st: AppState = Depends(get_state)):
        return {'marked': st.notifications.mark_all_read(universe)}

    @api.post('/notifications/{notification_id}/read', tags=['alerts'])
    def read_one(notification_id: int, st: AppState = Depends(get_state)):
        if not st.notifications.mark_read(notification_id):
            raise HTTPException(404, 'Notification not found')
        return st.notifications.get(notification_id)

    @api.get('/signals/schedule', tags=['alerts'])
    def signal_schedule(st: AppState = Depends(get_state)):
        schedule = st.signal_config['schedule']
        now = datetime.now().astimezone()
        return {
            'enabled': st.signal_config.get('enabled', True),
            'timezone': schedule.get('timezone'),
            'open': schedule.get('open'),
            'close': schedule.get('close'),
            'next': {u: [{'at': when.isoformat(), 'session': session}
                         for when, session in scan_times(schedule, u, now)[:2]] for u in UNIVERSES},
        }

    @api.get('/experiments/settings', tags=['performance'])
    def experiment_settings():
        return ALLOWED_SETTINGS

    @api.get('/{universe}', tags=['universe'])
    def describe(service: UniverseService = Depends(universe_service)):
        return service.describe()

    @api.post('/{universe}/analysis', status_code=202, tags=['analysis'])
    def start_analysis(body: AnalysisRequest, service: UniverseService = Depends(universe_service),
                       st: AppState = Depends(get_state)):
        job = st.jobs.submit('analysis', service.universe,
                             lambda job: service.run_analysis(job, top_n=body.top_n, symbols=body.symbols))
        return job.to_dict()

    @api.get('/{universe}/analysis/latest', tags=['analysis'])
    def latest_analysis(service: UniverseService = Depends(universe_service)):
        result = service.latest_analysis()
        if not result:
            raise HTTPException(404, 'No analysis has been run yet')
        return result

    @api.get('/{universe}/runs', tags=['analysis'])
    def list_runs(service: UniverseService = Depends(universe_service)):
        return service.store.list_runs(service.universe)

    @api.get('/{universe}/runs/{run_id}', tags=['analysis'])
    def get_run(run_id: str, service: UniverseService = Depends(universe_service)):
        result = service.run_detail(run_id)
        if not result:
            raise HTTPException(404, 'Run not found')
        return result

    @api.get('/{universe}/assets/{symbol}', tags=['analysis'])
    def asset(symbol: str, service: UniverseService = Depends(universe_service),
              st: AppState = Depends(get_state)):
        with st.jobs.lock(service.universe):
            result = service.asset_detail(symbol)
        if not result:
            raise HTTPException(404, f'No data for {symbol}')
        return result

    @api.post('/{universe}/signals/scan', status_code=202, tags=['alerts'])
    def scan(body: ScanRequest, service: UniverseService = Depends(universe_service),
             st: AppState = Depends(get_state)):
        job = st.jobs.submit('scan', service.universe, lambda job: service.scan_signals(job, body.session))
        return job.to_dict()

    @api.get('/{universe}/performance', tags=['performance'])
    def performance(source: str = 'backtest', backtest_id: Optional[str] = None,
                    service: UniverseService = Depends(universe_service)):
        if source not in ('live', 'backtest'):
            raise HTTPException(422, "source must be 'live' or 'backtest'")
        report = service.performance(source, backtest_id)
        if report is None:
            raise HTTPException(404, 'No predictions to compare yet; run a backtest first')
        return report

    @api.get('/{universe}/performance/predictions.csv', tags=['performance'])
    def performance_csv(source: str = 'backtest', backtest_id: Optional[str] = None,
                        service: UniverseService = Depends(universe_service)):
        csv = service.predictions_csv(source, backtest_id)
        if csv is None:
            raise HTTPException(404, 'No predictions to export')
        name = f"{service.universe}_{source}_{backtest_id or 'latest'}_predictions.csv"
        return PlainTextResponse(csv, media_type='text/csv',
                                 headers={'Content-Disposition': f'attachment; filename="{name}"'})

    @api.get('/{universe}/experiments', tags=['performance'])
    def list_experiments(service: UniverseService = Depends(universe_service)):
        cfg = service.pipeline.config.get('experiments', {})
        return {'lockbox_days': cfg.get('lockbox_days', 60), 'test_days': cfg.get('test_days', 250),
                'experiments': service.store.list_experiments(service.universe)}

    @api.post('/{universe}/experiments', status_code=202, tags=['performance'])
    def create_experiment(body: ExperimentRequest, service: UniverseService = Depends(universe_service),
                          st: AppState = Depends(get_state)):
        try:
            experiment_id = service.create_experiment(body.name, body.settings, body.top_n)
        except ValueError as e:
            raise HTTPException(422, str(e))
        job = st.jobs.submit('experiment', service.universe,
                             lambda job: service.run_experiment(job, experiment_id), dedupe=False)
        return {'experiment_id': experiment_id, 'job': job.to_dict()}

    @api.get('/{universe}/experiments/{experiment_id}', tags=['performance'])
    def get_experiment(experiment_id: str, service: UniverseService = Depends(universe_service)):
        experiment = service.store.get_experiment(experiment_id)
        if not experiment or experiment['universe'] != service.universe:
            raise HTTPException(404, 'Experiment not found')
        return experiment

    @api.post('/{universe}/experiments/{experiment_id}/lockbox', status_code=202, tags=['performance'])
    def lockbox(experiment_id: str, service: UniverseService = Depends(universe_service),
                st: AppState = Depends(get_state)):
        experiment = service.store.get_experiment(experiment_id)
        if not experiment or experiment['universe'] != service.universe:
            raise HTTPException(404, 'Experiment not found')
        if experiment['status'] != 'done':
            raise HTTPException(409, 'Run the experiment on the development period first')
        job = st.jobs.submit('lockbox', service.universe, lambda job: service.check_lockbox(job, experiment_id),
                             dedupe=False)
        return job.to_dict()

    @api.get('/{universe}/models', tags=['models'])
    def models(service: UniverseService = Depends(universe_service)):
        """Registered model versions with their scores, the champion, and whether it is pinned."""
        return service.models()

    @api.post('/{universe}/models/{version}/promote', tags=['models'])
    def promote_model(version: str, body: Optional[PromoteRequest] = None,
                      service: UniverseService = Depends(universe_service)):
        """Make a version the champion (roll back or forward). Pinned by default: analyses then use it as is."""
        return _registry_call(lambda: service.promote_model(version, pin=(body or PromoteRequest()).pin))

    @api.post('/{universe}/models/unpin', tags=['models'])
    def unpin_model(service: UniverseService = Depends(universe_service)):
        """Go back to training new models at every analysis."""
        return _registry_call(service.unpin_model)

    @api.get('/{universe}/volatility', tags=['analysis'])
    def volatility(service: UniverseService = Depends(universe_service)):
        return service.volatility()

    @api.get('/{universe}/market', tags=['analysis'])
    def market(service: UniverseService = Depends(universe_service)):
        try:
            return service.market()
        except Exception as e:
            logger.warning(f"Market data unavailable: {e}")
            return {'items': []}

    @api.get('/{universe}/track-record', tags=['track record'])
    def track_record(service: UniverseService = Depends(universe_service)):
        return service.track_record()

    @api.post('/{universe}/track-record/evaluate', status_code=202, tags=['track record'])
    def evaluate(service: UniverseService = Depends(universe_service), st: AppState = Depends(get_state)):
        job = st.jobs.submit('evaluate', service.universe, lambda job: {'evaluated_runs': service.evaluate_outcomes()})
        return job.to_dict()

    @api.post('/{universe}/backtests', status_code=202, tags=['backtests'])
    def start_backtest(body: BacktestRequest, service: UniverseService = Depends(universe_service),
                       st: AppState = Depends(get_state)):
        params = body.model_dump()
        job = st.jobs.submit('backtest', service.universe, lambda job: service.run_backtest(job, params))
        return job.to_dict()

    @api.get('/{universe}/backtests', tags=['backtests'])
    def list_backtests(service: UniverseService = Depends(universe_service)):
        return service.store.list_backtests(service.universe)

    @api.get('/{universe}/backtests/{backtest_id}', tags=['backtests'])
    def get_backtest(backtest_id: str, service: UniverseService = Depends(universe_service)):
        result = service.store.get_backtest(backtest_id)
        if not result or result['universe'] != service.universe:
            raise HTTPException(404, 'Backtest not found')
        return result

    app.include_router(api)

    # Serve the built Angular app, with client-side routes falling back to index.html
    index = os.path.join(settings.frontend_dist, 'index.html')
    if os.path.exists(index):
        @app.get('/{path:path}', include_in_schema=False)
        def frontend(path: str, request: Request):
            if path.startswith('api/'):
                return JSONResponse({'detail': 'Not Found'}, status_code=404)
            candidate = os.path.normpath(os.path.join(settings.frontend_dist, path))
            if path and candidate.startswith(os.path.normpath(settings.frontend_dist)) and os.path.isfile(candidate):
                return FileResponse(candidate)
            return FileResponse(index)

    return app


app = create_app()
