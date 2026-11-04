"""
Per-universe application service: runs analyses and backtests, records
predictions, scores them once their horizon has passed, and assembles the
data each dashboard page needs.

There is one ``UniverseService`` per asset class, each wrapping its own
pipeline (and therefore its own trained models).

The methods are grouped by domain in this package (``models``, ``forecasts``,
``portfolio``, ``track_record``, ``performance``); this module holds the
shared state, the analysis run and the helpers.
"""

import logging
import tempfile
from typing import Any, Dict, List, Optional

import pandas as pd

from api.jobs import Job
from api.notifications import Notifier
from api.serialization import snake_records, to_jsonable
from api.service.forecasts import ForecastsMixin
from api.service.models import ModelsMixin
from api.service.performance import PerformanceMixin
from api.service.portfolio import PortfolioMixin
from api.service.track_record import TrackRecordMixin
from api.settings import Settings
from api.store import NotificationStore, Store
from src.data.synthetic import SyntheticDataCollector
from src.prediction import create_pipeline
from src.signals import SignalDetector, detect_from_analysis, merge_signal_config

logger = logging.getLogger(__name__)

HISTORY_COLUMNS = {
    'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume',
    'SMA_20': 'sma_20', 'SMA_50': 'sma_50', 'SMA_200': 'sma_200',
    'BB_Upper': 'bb_upper', 'BB_Lower': 'bb_lower', 'RSI': 'rsi',
    'MACD': 'macd', 'MACD_Signal': 'macd_signal', 'Volatility_20d': 'volatility_20d',
}



class UniverseService(TrackRecordMixin, ForecastsMixin, PortfolioMixin, PerformanceMixin, ModelsMixin):
    def __init__(self, universe: str, settings: Settings, store: Store, collector=None,
                 notifier: Optional[Notifier] = None, registry=None, metrics=None):
        self.universe = universe
        self.metrics = metrics  # api.metrics.Metrics, optional
        self.registry = registry  # src.models.registry.ModelRegistry, or None when turned off
        self.loaded_version: Optional[str] = None
        self.settings = settings
        self.store = store
        if collector is None and settings.demo_mode:
            collector = SyntheticDataCollector(reversal=0.2, days=1260)  # 5 years, as live
        self.pipeline = create_pipeline(universe, settings.config_path, data_collector=collector)
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
            'model': p.model_kind,
            'ridge_alpha': p.config.get('ml_config', {}).get('cross_section', {}).get('ridge', {}).get('alpha'),
            'filters': p.filters,
            'portfolio': p.portfolio_config,
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
        try:
            if job:
                job.message = 'Forecasting price ranges'
            self.refresh_forecasts(prepared=self.prepared)
        except Exception as e:  # the analysis is complete without them
            logger.warning(f'Could not forecast {self.universe} price ranges: {e}')
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

    # ------------------------------------------------------------ forecasts

    def _closes(self, prepared: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, pd.Series]:
        if prepared:
            return {s: d['Close'] for s, d in prepared.items() if 'Close' in d}
        period = self.pipeline.universe_config.get('timeframe', '2y')
        raw = self.pipeline.data_collector.fetch_multiple_stocks(self.default_symbols(), period=period)
        return {s: d['Close'] for s, d in raw.items() if d is not None and not d.empty}

    # ------------------------------------------------------------ portfolio

    # ------------------------------------------------------------ long term

    def long_term_view(self) -> Optional[Dict[str, Any]]:
        """The latest analysis's long-term ranking (about a month ahead), with its own evidence."""
        analysis = self.latest_analysis()
        long_term = (analysis or {}).get('summary', {}).get('long_term')
        if not long_term:
            return None
        assets = [{
            'symbol': r['symbol'], 'name': r.get('company_name') or r['symbol'], 'sector': r.get('sector'),
            'price': r.get('current_price'), 'score': r.get('long_score'), 'probability': r.get('long_probability'),
            'short_rank': r.get('rank'), 'picked': bool(r.get('picked')), 'volatility': r.get('volatility'),
        } for r in analysis['rankings'] if r.get('long_score') is not None]
        assets.sort(key=lambda a: -a['score'])
        for rank, a in enumerate(assets, 1):
            a['rank'] = rank
        return to_jsonable({'data_date': analysis['run']['data_date'], 'short_horizon_days': self.pipeline.horizon,
                            **long_term, 'assets': assets})

    # ---------------------------------------------------------------- brief

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

    # ------------------------------------------------------------- outcomes

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
            'forecast': self.asset_forecast(symbol),
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

    # ---------------------------------------------------------- performance

    # ---------------------------------------------------------- experiments

    def seed_demo(self, job: Optional[Job] = None) -> Dict[str, Any]:
        """Populate a fresh demo dashboard: simulated history, then a current analysis."""
        if job:
            job.message = 'Building simulated track record'
        backtest = self.run_backtest(job, {'test_days': 150}, record_simulated=True)
        analysis = self.run_analysis(job)
        if job:
            job.message = 'Replaying price ranges on past dates'
        try:
            self.backfill_forecasts(self.prepared)
        except Exception as e:
            logger.warning(f'Could not replay {self.universe} forecasts: {e}')
        # Back-fill a few weeks of alerts so the Alerts page has something to show
        signals = self.scan_signals(job, session='close', lookback=30)
        return {**backtest, **analysis, 'alerts': signals['new_alerts']}
