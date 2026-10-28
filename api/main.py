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
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from api.jobs import JobManager
from api.service import UniverseService
from api.settings import Settings
from api.store import Store
from src.prediction import UNIVERSES

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


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings.database_path)
        self.jobs = JobManager(max_workers=2)
        self.services: Dict[str, UniverseService] = {}

    def service(self, universe: str) -> UniverseService:
        if universe not in UNIVERSES:
            raise HTTPException(404, f"Unknown universe '{universe}'")
        if universe not in self.services:
            self.services[universe] = UniverseService(universe, self.settings, self.store)
        return self.services[universe]


async def scheduler_loop(state: AppState) -> None:
    """Run the daily analysis for each configured universe at the configured local time."""
    config = state.service('stocks').pipeline.config.get('scheduler', {})
    hour, minute = (int(x) for x in config.get('time', '22:30').split(':'))
    universes = [u for u in config.get('universes', UNIVERSES) if u in UNIVERSES]
    while True:
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        for universe in universes:
            service = state.service(universe)
            state.jobs.submit('analysis', universe, lambda job, s=service: s.run_analysis(job))
            logger.info(f"Scheduled analysis started for {universe}")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = []
        if settings.demo_mode and settings.seed_demo:
            for universe in UNIVERSES:
                if not state.store.has_runs(universe):
                    service = state.service(universe)
                    state.jobs.submit('seed', universe, lambda job, s=service: s.seed_demo(job))
        if state.service('stocks').pipeline.config.get('scheduler', {}).get('enabled'):
            tasks.append(asyncio.create_task(scheduler_loop(state)))
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

    def get_state() -> AppState:
        return state

    def universe_service(universe: str = Path(..., description="'stocks' or 'crypto'"),
                         st: AppState = Depends(get_state)) -> UniverseService:
        return st.service(universe)

    api = APIRouter(prefix='/api')

    @api.get('/health', tags=['meta'])
    def health():
        return {'status': 'ok', 'version': VERSION, 'demo': settings.demo_mode}

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
