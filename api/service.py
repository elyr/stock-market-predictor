"""
Per-universe application service: runs analyses and backtests, records
predictions, scores them once their horizon has passed, and assembles the
data each dashboard page needs.

There is one ``UniverseService`` per asset class, each wrapping its own
pipeline (and therefore its own trained models).
"""

import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from api.jobs import Job
from api.notifications import Notifier
from api.serialization import snake_records, to_jsonable
from api.settings import Settings
from api.store import NotificationStore, Store
from src.backtest import Backtester
from src.backtest.backtester import STRATEGY_LABELS
from src.data.synthetic import SyntheticDataCollector
from src.prediction import create_pipeline
from src.signals import SignalDetector, detect_from_analysis, merge_signal_config
from src.evaluation import ExperimentRunner, build_report, normalize_log, validate_settings
from src.evaluation.comparator import LOG_COLUMNS

logger = logging.getLogger(__name__)

HISTORY_COLUMNS = {
    'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume',
    'SMA_20': 'sma_20', 'SMA_50': 'sma_50', 'SMA_200': 'sma_200',
    'BB_Upper': 'bb_upper', 'BB_Lower': 'bb_lower', 'RSI': 'rsi',
    'MACD': 'macd', 'MACD_Signal': 'macd_signal', 'Volatility_20d': 'volatility_20d',
}


class UniverseService:
    def __init__(self, universe: str, settings: Settings, store: Store, collector=None,
                 notifier: Optional[Notifier] = None, registry=None, metrics=None):
        self.universe = universe
        self.metrics = metrics  # api.metrics.Metrics, optional
        self.registry = registry  # src.models.registry.ModelRegistry, or None when turned off
        self.loaded_version: Optional[str] = None
        self.settings = settings
        self.store = store
        if collector is None and settings.demo_mode:
            collector = SyntheticDataCollector(reversal=0.2)
        self.pipeline = create_pipeline(universe, settings.config_path, data_collector=collector)
        if settings.demo_mode:
            self.pipeline.use_sentiment = False
        self.prepared: Dict[str, pd.DataFrame] = {}
        self.signal_config = merge_signal_config(self.pipeline.config.get('signals'))
        self.detector = SignalDetector(universe, self.signal_config)
        self.notifier = notifier or Notifier(NotificationStore(store),
                                             cooldown_hours=self.signal_config['cooldown_hours'])

    # ------------------------------------------------------------- metadata

    def describe(self) -> Dict[str, Any]:
        p = self.pipeline
        latest = self.store.latest_run(self.universe)
        return {
            'key': self.universe,
            'label': p.label,
            'symbols': p.symbols,
            'symbol_count': len(p.symbols),
            'horizon_days': p.horizon,
            'target': p.predictor.config['training'].get('target'),
            'periods_per_year': p.periods_per_year,
            'top_picks': p.ranking_config.get('top_picks', 10),
            'weights': p.weights,
            'filters': p.filters,
            'portfolio': p.portfolio_config,
            'use_sentiment': p.use_sentiment,
            'backtest_defaults': p.config.get('backtest', {}),
            'latest_run_at': latest['created_at'] if latest else None,
            'demo': self.settings.demo_mode,
        }

    def default_symbols(self) -> List[str]:
        # Demo mode keeps runs quick on modest hardware
        return self.pipeline.symbols[:40] if self.settings.demo_mode else self.pipeline.symbols

    # ------------------------------------------------------------- analysis

    def run_analysis(self, job: Optional[Job] = None, top_n: Optional[int] = None,
                     symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """Rank the universe, store every prediction, then score any matured past runs."""
        model = self._prepare_models(job)
        result = self.pipeline.get_top_10_recommendations(symbols or self.default_symbols(), top_n=top_n)
        rankings = result['full_rankings']
        if rankings.empty:
            raise RuntimeError('No assets passed the filters or no data was available')

        self.prepared = dict(self.pipeline.last_prepared)
        previous = self.store.latest_run(self.universe)
        previous_picks = [p['symbol'] for p in self.store.predictions(previous['id'], picked_only=True)] \
            if previous else None
        weights = result['top_10'].set_index('Symbol')['Weight'].to_dict()
        payloads = snake_records(rankings)
        predictions = [{
            'symbol': row['symbol'],
            'rank': rank,
            'picked': row['symbol'] in weights,
            'weight': float(weights[row['symbol']]) if row['symbol'] in weights else None,
            'composite_score': row['composite_score'],
            'ml_probability': row.get('ml_probability'),
            'entry_price': row['current_price'],
            'payload': {**row, 'weight': float(weights[row['symbol']]) if row['symbol'] in weights else None},
        } for rank, row in enumerate(payloads, 1)]
        summary = to_jsonable(result['analysis_summary'])
        if not model['reused']:
            model.update(self._register_models(summary))
        summary['model'] = model
        run_id = self.store.save_run(self.universe, summary['data_date'], self.pipeline.horizon,
                                     len(weights), summary, predictions, demo=self.settings.demo_mode)

        if job:
            job.message = 'Scoring earlier predictions that have matured'
        evaluated = self.evaluate_outcomes(self.prepared)
        alerts = self.notifier.publish(self.universe, detect_from_analysis(
            self.universe, [p['payload'] for p in predictions], previous_picks, summary['data_date'],
            self.signal_config), session='analysis')
        self._count_alerts(alerts)
        return {'run_id': run_id, 'evaluated_runs': evaluated, 'new_alerts': len(alerts)}

    # ------------------------------------------------------- model registry

    def _prepare_models(self, job: Optional[Job]) -> Dict[str, Any]:
        """
        Decide which models this analysis uses: the pinned champion from the
        registry (loaded once, then kept in memory), or new ones trained now.
        """
        registry = self.registry
        if registry is not None and registry.pinned(self.universe):
            version = registry.champion(self.universe)
            if version is None:
                raise RuntimeError('The model is pinned but no version is marked as champion. '
                                   'Promote a version or unpin the model.')
            if self.loaded_version != version or not self.pipeline.reuse_models:
                if job:
                    job.message = f'Loading {self.pipeline.label} model version {version}'
                with tempfile.TemporaryDirectory(prefix=f'ledger-{self.universe}-') as tmp:
                    self.pipeline.import_models(registry.download(self.universe, version, tmp))
                self.loaded_version = version
            if job:
                job.message = f'Fetching prices and ranking with model version {version}'
            return {'version': version, 'reused': True, 'registry': registry.name(self.universe)}

        self.pipeline.reuse_models = False
        self.loaded_version = None
        if job:
            job.message = f'Fetching prices and training {self.pipeline.label} models'
        return {'version': None, 'reused': False,
                'registry': registry.name(self.universe) if registry is not None else None}

    def _register_models(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Record the models just trained as a new registry version (the champion unless pinned meanwhile)."""
        registry = self.registry
        if registry is None or not self.pipeline.ml_trained:
            return {}
        p = self.pipeline
        params = {
            'universe': self.universe, 'data_date': summary.get('data_date'), 'horizon_days': p.horizon,
            'target': summary.get('target'), 'assets': summary.get('total_analyzed'),
            'models': ','.join(summary.get('ml_models_used') or []),
            'features': len(p.predictor.feature_columns), 'demo': self.settings.demo_mode,
            'weights': ','.join(f'{k}={v}' for k, v in sorted(p.weights.items())),
        }
        metrics = {'quality': summary.get('model_quality') or {},
                   'volatility': {k: v for k, v in (summary.get('volatility_model') or {}).items() if k != 'horizon'},
                   'test_accuracy': {k: v for k, v in (summary.get('ml_test_accuracy') or {}).items()}}
        tags = {'git_commit': git_commit()}
        try:
            with tempfile.TemporaryDirectory(prefix=f'ledger-{self.universe}-') as tmp:
                p.export_models(tmp)
                # Promote unless someone pinned a version while this analysis was running
                version = registry.register(self.universe, tmp, params, metrics, tags,
                                            promote=not registry.pinned(self.universe))
            return {'version': version['version'], 'run_id': version['run_id']}
        except Exception as e:  # the analysis is still useful without the registry
            logger.warning(f'Could not register the {self.universe} models: {e}')
            return {'error': f'Not registered: {e}'}

    def models(self) -> Dict[str, Any]:
        if self.registry is None:
            return {'enabled': False, 'versions': [], 'champion': None, 'pinned': False}
        return {**self.registry.summary(self.universe), 'loaded_version': self.loaded_version}

    def promote_model(self, version: str, pin: bool = True) -> Dict[str, Any]:
        self._require_registry()
        self.registry.promote(self.universe, version, pin=pin)
        return self.models()

    def unpin_model(self) -> Dict[str, Any]:
        self._require_registry()
        self.registry.set_pinned(self.universe, False)
        return self.models()

    def _require_registry(self) -> None:
        if self.registry is None:
            raise RuntimeError('The model registry is turned off (MODEL_REGISTRY=off)')

    # -------------------------------------------------------------- signals

    def scan_signals(self, job: Optional[Job] = None, session: str = 'close', lookback: int = 1) -> Dict[str, Any]:
        """
        Look for unusual moves, volume, gaps and market-wide moves in the latest
        prices, and publish anything new as notifications.

        Args:
            session: 'open' (gaps and early moves) or 'close' (everything)
            lookback: number of recent bars to check (more than 1 back-fills history)
        """
        if job:
            job.message = f'Scanning {self.pipeline.label} for unusual moves'
        raw = self.pipeline.data_collector.fetch_multiple_stocks(self.default_symbols(), period='6mo')
        latest = self.store.latest_run(self.universe)
        names, holdings = {}, []
        if latest:
            for p in self.store.predictions(latest['id']):
                names[p['symbol']] = p['payload'].get('company_name') or p['symbol']
                if p['picked']:
                    holdings.append(p['symbol'])
        if self.universe == 'crypto':
            names = {s: self.pipeline.asset_metadata(s, None)['name'] for s in raw} | names
        signals = self.detector.scan(raw, session=session, lookback=lookback, names=names, holdings=holdings)
        created = self.notifier.publish(self.universe, signals, session=session)
        self._count_alerts(created)
        return {'detected': len(signals), 'new_alerts': len(created), 'session': session,
                'assets_scanned': len(raw)}

    def _count_alerts(self, alerts) -> None:
        if self.metrics and alerts:
            self.metrics.alerts_published(self.universe, alerts)

    def latest_analysis(self) -> Optional[Dict[str, Any]]:
        run = self.store.latest_run(self.universe)
        if not run:
            return None
        return self._run_view(run)

    def run_detail(self, run_id: str) -> Optional[Dict[str, Any]]:
        run = self.store.get_run(run_id)
        if not run or run['universe'] != self.universe:
            return None
        return self._run_view(run)

    def _run_view(self, run: Dict[str, Any]) -> Dict[str, Any]:
        predictions = self.store.predictions(run['id'])
        rankings = []
        for p in predictions:
            item = dict(p['payload'])
            item.update({'rank': p['rank'], 'picked': p['picked'], 'weight': p['weight'],
                         'realized_return': p['realized_return']})
            rankings.append(item)
        summary = run.pop('summary')
        return {'run': run, 'summary': summary,
                'picks': [r for r in rankings if r['picked']], 'rankings': rankings}

    # ------------------------------------------------------------- outcomes

    def evaluate_outcomes(self, prepared: Optional[Dict[str, pd.DataFrame]] = None) -> int:
        """
        Fill in realised results for past runs whose horizon has passed.

        Each asset's return runs from its entry close to the close ``horizon``
        rows later in its own price history.
        """
        pending = [r for r in self.store.pending_runs(self.universe) if not r['simulated']]
        if not pending:
            return 0
        if prepared is None:
            symbols = sorted({p['symbol'] for r in pending for p in self.store.predictions(r['id'])})
            raw = self.pipeline.data_collector.fetch_multiple_stocks(symbols, period='1y')
            closes = {s: d['Close'] for s, d in raw.items() if d is not None}
        else:
            closes = {s: d['Close'] for s, d in prepared.items()}

        evaluated = 0
        for run in pending:
            entry = pd.Timestamp(run['data_date'])
            horizon = int(run['horizon'])
            predictions = self.store.predictions(run['id'])
            returns, exit_dates = {}, []
            for p in predictions:
                series = closes.get(p['symbol'])
                if series is None or entry not in series.index:
                    continue
                pos = series.index.get_loc(entry)
                if pos + horizon >= len(series):
                    continue
                exit_price = series.iloc[pos + horizon]
                base = p['entry_price'] or series.iloc[pos]
                returns[p['symbol']] = float(exit_price / base - 1)
                exit_dates.append(series.index[pos + horizon])
            if len(returns) < max(2, 0.8 * len(predictions)):
                continue  # not matured yet (or data missing)

            picked = [p for p in predictions if p['picked'] and p['symbol'] in returns]
            total_weight = sum(p['weight'] or 0 for p in picked) or 1.0
            portfolio = sum((p['weight'] or 0) / total_weight * returns[p['symbol']] for p in picked)
            universe_return = float(np.mean(list(returns.values())))
            scored = [(p['composite_score'], returns[p['symbol']]) for p in predictions if p['symbol'] in returns]
            ic = float(spearmanr(*zip(*scored))[0]) if len(scored) >= 5 else None
            self.store.record_outcome(run['id'], str(max(exit_dates).date()), returns,
                                      float(portfolio), universe_return, ic)
            evaluated += 1
        return evaluated

    def track_record(self) -> Dict[str, Any]:
        """Summary of every scored run: live predictions and, in demo mode, simulated history."""
        runs = self.store.list_runs(self.universe, limit=1000)

        def summarize(items: List[Dict[str, Any]]) -> Dict[str, Any]:
            done = sorted([r for r in items if r['evaluated_at']], key=lambda r: r['data_date'])
            if not done:
                return {'evaluated': 0, 'pending': sum(1 for r in items if not r['evaluated_at'])}
            excess = np.array([r['excess_return'] for r in done])
            ics = np.array([r['rank_ic'] for r in done if r['rank_ic'] is not None])
            portfolio_curve = np.cumprod([1 + r['portfolio_return'] for r in done]) - 1
            universe_curve = np.cumprod([1 + r['universe_return'] for r in done]) - 1
            return {
                'evaluated': len(done),
                'pending': sum(1 for r in items if not r['evaluated_at']),
                'avg_excess_return': float(excess.mean()),
                'excess_t_stat': float(excess.mean() / excess.std() * np.sqrt(len(excess)))
                if len(excess) > 1 and excess.std() > 0 else None,
                'hit_rate': float((excess > 0).mean()),
                'avg_rank_ic': float(ics.mean()) if len(ics) else None,
                'curve': [{'date': r['exit_date'] or r['data_date'], 'portfolio': float(p), 'universe': float(u)}
                          for r, p, u in zip(done, portfolio_curve, universe_curve)],
            }

        live = [r for r in runs if not r['simulated']]
        simulated = [r for r in runs if r['simulated']]
        return {'live': summarize(live), 'simulated': summarize(simulated), 'runs': to_jsonable(runs)}

    # ---------------------------------------------------------------- assets

    def asset_detail(self, symbol: str) -> Optional[Dict[str, Any]]:
        symbol = symbol.upper()
        data = self.prepared.get(symbol)
        if data is None:
            fetched = self.pipeline.fetch_and_prepare_data([symbol])
            data = fetched.get(symbol)
        if data is None or data.empty:
            return None
        history = data[[c for c in HISTORY_COLUMNS if c in data.columns]].tail(250).rename(columns=HISTORY_COLUMNS)
        history = history.reset_index().rename(columns={'index': 'date', 'Date': 'date'})
        history['date'] = pd.to_datetime(history['date']).dt.strftime('%Y-%m-%d')

        latest = self.latest_analysis()
        current = next((r for r in latest['rankings'] if r['symbol'] == symbol), None) if latest else None
        return {
            'symbol': symbol,
            'universe': self.universe,
            'name': self.pipeline.asset_metadata(symbol, None)['name'] if self.universe == 'crypto'
            else (current or {}).get('company_name', symbol),
            'history': to_jsonable(history.to_dict(orient='records')),
            'latest': current,
            'run': latest['run'] if latest else None,
            'signals': self.pipeline.describe_signals(data),
        }

    def volatility(self) -> Dict[str, Any]:
        latest = self.latest_analysis()
        if not latest:
            return {'model': None, 'assets': []}
        assets = [{k: r.get(k) for k in ('symbol', 'company_name', 'sector', 'current_price', 'volatility',
                                          'vol_forecast', 'vol_up_probability')} for r in latest['rankings']]
        assets.sort(key=lambda a: -(a['vol_up_probability'] or 0))
        return {'model': latest['summary'].get('volatility_model'), 'assets': assets,
                'data_date': latest['run']['data_date'],
                'horizon_days': (latest['summary'].get('volatility_model') or {}).get('horizon')}

    def market(self) -> Dict[str, Any]:
        """Benchmark moves for the dashboard header."""
        if self.universe == 'crypto':
            items = []
            for symbol in ('BTC-USD', 'ETH-USD', 'SOL-USD'):
                data = self.prepared.get(symbol)
                if data is None:
                    data = self.pipeline.data_collector.fetch_stock_data(symbol, period='1mo')
                if data is None or len(data) < 2:
                    continue
                price, prev = float(data['Close'].iloc[-1]), float(data['Close'].iloc[-2])
                items.append({'symbol': symbol, 'name': self.pipeline.asset_metadata(symbol, None)['name'],
                              'price': price, 'change_pct': (price / prev - 1) * 100})
            return {'items': items}
        data = self.pipeline.data_collector.fetch_market_data() or {}
        return {'items': [{'symbol': s, 'name': v['name'], 'price': v['price'], 'change_pct': v['change_pct']}
                          for s, v in data.items()]}

    # ------------------------------------------------------------- backtests

    def run_backtest(self, job: Optional[Job] = None, params: Optional[Dict[str, Any]] = None,
                     record_simulated: bool = False) -> Dict[str, Any]:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        symbols = params.pop('symbols', None) or self.default_symbols()
        if job:
            job.message = f'Simulating {self.pipeline.label} picks period by period'
        tester = Backtester.from_config(self.pipeline, **params)
        result = tester.run_symbols(symbols)
        backtest_id = self._save_backtest(result, {**params, 'symbols': len(symbols)})
        if record_simulated:
            self._record_simulated_runs(result)
        return {'backtest_id': backtest_id}

    def _save_backtest(self, result, params: Dict[str, Any]) -> str:
        """Store a backtest's summary and its full prediction log."""
        backtest_id = self.store.save_backtest(self.universe, params, serialize_backtest(result),
                                               demo=self.settings.demo_mode)
        log = normalize_log(result.predictions)
        if not log.empty:
            log = log.assign(date=log['date'].dt.strftime('%Y-%m-%d'))
            self.store.save_backtest_predictions(backtest_id, to_jsonable(log.to_dict(orient='records')))
        return backtest_id

    # ---------------------------------------------------------- performance

    def live_log(self) -> pd.DataFrame:
        """Scored live predictions in the comparator's log layout."""
        rows = []
        for run in self.store.list_runs(self.universe, limit=1000):
            if run['simulated'] or not run['evaluated_at']:
                continue
            predictions = self.store.predictions(run['id'])
            vols = [p['payload'].get('volatility') for p in predictions if p['payload'].get('volatility')]
            for p in predictions:
                if p['realized_return'] is None:
                    continue
                payload = p['payload']
                rows.append({
                    'date': run['data_date'], 'symbol': p['symbol'], 'sector': payload.get('sector'),
                    'score': p['composite_score'], 'rank': p['rank'], 'picked': p['picked'], 'weight': p['weight'],
                    'ml_probability': p['ml_probability'], 'technical_score': payload.get('technical_score'),
                    'momentum_score': payload.get('momentum_score'), 'volume_score': payload.get('volume_score'),
                    'future_return': p['realized_return'], 'universe_return': run['universe_return'],
                    'universe_volatility': float(np.mean(vols)) if vols else None,
                })
        return normalize_log(pd.DataFrame(rows))

    def performance_sources(self) -> List[Dict[str, Any]]:
        """Live predictions, then regular backtests, then experiment runs (newest first)."""
        regular, experiment_runs = [], []
        for b in self.store.backtests_with_predictions(self.universe):
            params = b['params']
            item = {'source': 'backtest', 'id': b['id'], 'created_at': b['created_at']}
            if params.get('experiment'):
                period = 'locked period' if params.get('period') == 'locked' else 'development period'
                experiment_runs.append({**item, 'label': f"Experiment: {params['experiment']} ({period})"})
            else:
                regular.append({**item, 'label': f"Backtest of {b['created_at'][:16].replace('T', ' ')}"})
        return [{'source': 'live', 'id': None, 'label': 'Live predictions'}, *regular, *experiment_runs]

    def _default_backtest_id(self) -> Optional[str]:
        """The newest regular backtest, or the newest experiment run if there is none."""
        backtests = [s for s in self.performance_sources() if s['source'] == 'backtest']
        return backtests[0]['id'] if backtests else None

    def _log_for(self, source: str, backtest_id: Optional[str]) -> Optional[pd.DataFrame]:
        if source == 'live':
            return self.live_log()
        backtest_id = backtest_id or self._default_backtest_id()
        if not backtest_id:
            return None
        rows = self.store.backtest_predictions(backtest_id)
        return None if rows is None else normalize_log(pd.DataFrame(rows))

    def performance(self, source: str = 'backtest', backtest_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Predicted-versus-actual report for live predictions or a stored backtest."""
        log = self._log_for(source, backtest_id)
        if log is None:
            return None
        if source == 'backtest' and not backtest_id:
            backtest_id = self._default_backtest_id()
        report = to_jsonable(build_report(log))
        return {'source': source, 'backtest_id': backtest_id, 'sources': self.performance_sources(), **report}

    def predictions_csv(self, source: str = 'backtest', backtest_id: Optional[str] = None) -> Optional[str]:
        log = self._log_for(source, backtest_id)
        if log is None:
            return None
        out = log.assign(date=pd.to_datetime(log['date']).dt.strftime('%Y-%m-%d'))[LOG_COLUMNS]
        return out.to_csv(index=False, float_format='%.6g')

    # ---------------------------------------------------------- experiments

    def experiment_runner(self) -> ExperimentRunner:
        cfg = self.pipeline.config.get('experiments', {})
        return ExperimentRunner(self.universe, self.settings.config_path, self.pipeline.data_collector,
                                lockbox_days=cfg.get('lockbox_days', 60), test_days=cfg.get('test_days', 250),
                                symbols=self.default_symbols())

    def create_experiment(self, name: str, settings: Dict[str, Any], top_n: Optional[int] = None) -> str:
        validate_settings(self.universe, settings)  # raises ValueError before anything is stored
        return self.store.create_experiment(self.universe, name, settings, top_n)

    def run_experiment(self, job: Optional[Job], experiment_id: str) -> Dict[str, Any]:
        experiment = self.store.get_experiment(experiment_id)
        self.store.update_experiment(experiment_id, status='running')
        if job:
            job.message = f"Running '{experiment['name']}' on the development period"
        try:
            out = self.experiment_runner().run_development(experiment['settings'], top_n=experiment['top_n'])
        except Exception as e:
            self.store.update_experiment(experiment_id, status='failed', error=str(e))
            raise
        backtest_id = self._save_backtest(out['result'], {'experiment': experiment['name'], 'period': 'development'})
        self.store.update_experiment(experiment_id, status='done', dev_backtest_id=backtest_id,
                                     dev_json=self._experiment_payload(out))
        return {'experiment_id': experiment_id, 'backtest_id': backtest_id}

    def check_lockbox(self, job: Optional[Job], experiment_id: str) -> Dict[str, Any]:
        experiment = self.store.get_experiment(experiment_id)
        if experiment['lockbox']:
            return {'experiment_id': experiment_id, 'already_checked': True}
        if job:
            job.message = f"Checking '{experiment['name']}' on the locked period"
        out = self.experiment_runner().run_lockbox(experiment['settings'], top_n=experiment['top_n'])
        backtest_id = self._save_backtest(out['result'], {'experiment': experiment['name'], 'period': 'locked'})
        self.store.update_experiment(experiment_id, lockbox_backtest_id=backtest_id,
                                     lockbox_json=self._experiment_payload(out),
                                     lockbox_checked_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        return {'experiment_id': experiment_id, 'backtest_id': backtest_id}

    @staticmethod
    def _experiment_payload(out: Dict[str, Any]) -> Dict[str, Any]:
        report = out['summary']['report']
        return to_jsonable({
            'headline': out['summary']['headline'],
            'summary': report['summary'],
            'components': report['components'],
            'deciles': report['deciles'],
            'windows': {k: str(v.date()) for k, v in out['windows'].items()},
        })

    def _record_simulated_runs(self, result) -> None:
        """Store each backtest period as a simulated, already-scored run (demo track record)."""
        if result.picks.empty:
            return
        for date, group in result.picks.groupby('date'):
            period = result.daily.loc[date]
            predictions = [{'symbol': p['symbol'], 'rank': int(p['rank']), 'picked': True,
                            'weight': float(p['weight']), 'composite_score': float(p['score']),
                            'entry_price': None, 'realized_return': float(p['return']),
                            'payload': {'symbol': p['symbol'], 'composite_score': float(p['score'])}}
                           for _, p in group.iterrows()]
            run_id = self.store.save_run(self.universe, str(date.date()), self.pipeline.horizon, len(group),
                                         {'simulated_from_backtest': True}, predictions,
                                         demo=True, simulated=True, created_at=f"{date.date()}T00:00:00+00:00")
            exit_date = date + pd.Timedelta(days=self.pipeline.horizon * (7 / 5 if self.universe == 'stocks' else 1))
            ic = period.get('composite_ic')
            self.store.record_outcome(run_id, str(exit_date.date()),
                                      {p['symbol']: p['realized_return'] for p in predictions},
                                      float(period['composite']), float(period['universe']),
                                      None if pd.isna(ic) else float(ic))

    def seed_demo(self, job: Optional[Job] = None) -> Dict[str, Any]:
        """Populate a fresh demo dashboard: simulated history, then a current analysis."""
        if job:
            job.message = 'Building simulated track record'
        backtest = self.run_backtest(job, {'test_days': 150}, record_simulated=True)
        analysis = self.run_analysis(job)
        # Back-fill a few weeks of alerts so the Alerts page has something to show
        signals = self.scan_signals(job, session='close', lookback=30)
        return {**backtest, **analysis, 'alerts': signals['new_alerts']}


def git_commit() -> Optional[str]:
    """The commit the app runs from: GIT_COMMIT (set in the image) or git itself."""
    commit = os.environ.get('GIT_COMMIT')
    if commit:
        return commit
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True,
                              timeout=5, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                              ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def serialize_backtest(result) -> Dict[str, Any]:
    """Backtest result as JSON: settings, metrics, IC, equity curves, periods and recent picks."""
    daily = result.daily
    curves = {}
    for column, label in STRATEGY_LABELS.items():
        if column in daily.columns and daily[column].notna().any():
            curves[column] = {'label': label,
                              'values': to_jsonable(((1 + daily[column].fillna(0)).cumprod() - 1).tolist())}
    metrics = [{'strategy': name, **to_jsonable(row.to_dict())} for name, row in result.metrics.iterrows()]
    composite = result.metrics.loc['Composite after costs'] if 'Composite after costs' in result.metrics.index else None
    headline = {
        'annualized_return': to_jsonable(composite['annualized_return']) if composite is not None else None,
        'excess_t_stat': to_jsonable(composite['excess_t_stat']) if composite is not None else None,
        'avg_excess_bps': to_jsonable(composite['avg_excess_bps']) if composite is not None else None,
        'ic_mean': to_jsonable(result.ic.get('Composite (no costs)', {}).get('ic_mean')),
    }
    periods = daily.reset_index()
    periods['date'] = periods['date'].dt.strftime('%Y-%m-%d')
    picks = result.picks.copy()
    if not picks.empty:
        picks['date'] = picks['date'].dt.strftime('%Y-%m-%d')
    return {
        'settings': to_jsonable(result.settings),
        'headline': headline,
        'metrics': metrics,
        'ic': [{'score': name, **to_jsonable(values)} for name, values in result.ic.items()],
        'dates': periods['date'].tolist(),
        'curves': curves,
        'periods': to_jsonable(periods.to_dict(orient='records')),
        'picks': to_jsonable(picks.tail(200).to_dict(orient='records')) if not picks.empty else [],
    }
