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
from api.settings import Settings, registry_settings
from api.store import NotificationStore, Store
from src.backtest import Backtester
from src.backtest.backtester import STRATEGY_LABELS
from src.data.synthetic import SyntheticDataCollector
from src.prediction import create_pipeline
from src.signals import SignalDetector, detect_from_analysis, merge_signal_config
from src.evaluation import ExperimentRunner, build_report, normalize_log, validate_settings
from src.evaluation.comparator import LOG_COLUMNS
from src.models.forecast import RangeForecaster, horizon_labels, horizons_for, inside, reliability
from src.personal import brief as brief_rules
from src.personal.portfolio import (DEFAULT_RULES, TransactionError, apply_transactions, portfolio_volatility,
                                    risk_label, risk_warnings, value_history, weekly_range)

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

    # ------------------------------------------------------------ forecasts

    def _closes(self, prepared: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, pd.Series]:
        if prepared:
            return {s: d['Close'] for s, d in prepared.items() if 'Close' in d}
        period = self.pipeline.universe_config.get('timeframe', '2y')
        raw = self.pipeline.data_collector.fetch_multiple_stocks(self.default_symbols(), period=period)
        return {s: d['Close'] for s, d in raw.items() if d is not None and not d.empty}

    def _forecaster(self) -> RangeForecaster:
        """The range model with this universe's horizons (``forecast_horizons`` in the config adds or replaces some)."""
        ppy = self.pipeline.periods_per_year
        overrides = self.pipeline.universe_config.get('forecast_horizons') or {}
        return RangeForecaster(periods_per_year=ppy, horizons=horizons_for(ppy, overrides))

    def refresh_forecasts(self, job: Optional[Job] = None,
                          prepared: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, Any]:
        """
        Fit the range model on this universe's history, store the ranges from
        the latest prices, and score earlier ranges whose window has passed.
        """
        if job:
            job.message = f'Fetching {self.pipeline.label} prices'
        closes = self._closes(prepared)
        if not closes:
            raise RuntimeError('No prices available')
        if job:
            job.message = 'Scoring earlier forecasts'
        scored = self.evaluate_forecasts(closes)
        if job:
            job.message = 'Forecasting price ranges'
        forecaster = self._forecaster()
        evaluation = forecaster.fit(closes)
        rows = forecaster.predict(closes)
        if not rows:
            raise RuntimeError('Not enough history to forecast')
        base_date = max(r['base_date'] for r in rows)
        summary = to_jsonable({
            'method': 'Volatility ranges with conformal calibration',
            'horizons': forecaster.horizons,
            'labels': horizon_labels(self.pipeline.periods_per_year, forecaster.horizons),
            'evaluation': evaluation, 'quantiles': forecaster.quantiles, 'assets': len(closes),
        })
        batch_id = self.store.save_forecast_batch(self.universe, base_date, summary, rows)
        return {'batch_id': batch_id, 'forecasts': len(rows), 'scored': scored}

    def evaluate_forecasts(self, closes: Dict[str, pd.Series]) -> int:
        """Record the outcome of every live forecast whose window has passed."""
        scored = 0
        for f in self.store.open_forecasts(self.universe):
            close = closes.get(f['symbol'])
            if close is None:
                continue
            close = close.dropna()
            base = pd.Timestamp(f['base_date'])
            if base not in close.index:
                continue
            position = close.index.get_loc(base)
            if position + f['days'] >= len(close):
                continue  # not over yet
            realized = float(close.iloc[position + f['days']])
            self.store.record_forecast_outcome(f['batch_id'], f['symbol'], f['horizon'],
                                               str(close.index[position + f['days']].date()), realized,
                                               **inside(realized, f))
            scored += 1
        return scored

    def backfill_forecasts(self, prepared: Optional[Dict[str, pd.DataFrame]] = None, periods: int = 60) -> int:
        """Give a new (demo) dashboard a simulated history: ranges replayed on past dates, already scored."""
        closes = self._closes(prepared)
        forecaster = self._forecaster()
        records = forecaster.backtest(closes, periods=periods)
        by_date: Dict[str, List[Dict[str, Any]]] = {}
        for r in records:
            by_date.setdefault(r['base_date'], []).append(r)
        for day, rows in sorted(by_date.items()):
            self.store.save_forecast_batch(self.universe, day, {'simulated': True}, rows, simulated=True,
                                           created_at=f'{day}T00:00:00+00:00')
        return len(records)

    def forecast_view(self) -> Optional[Dict[str, Any]]:
        """The latest ranges for every asset, with how reliable earlier ranges were."""
        batch = self.store.latest_forecast_batch(self.universe)
        if not batch:
            return None
        summary = batch['summary']
        labels = summary.get('labels', {})
        horizons = [{'key': k, 'days': d, 'label': labels.get(k, k)} for k, d in summary['horizons'].items()]

        scored = self.store.scored_forecasts(self.universe)
        live = [r for r in scored if not r['simulated']]
        simulated = [r for r in scored if r['simulated']]
        overall = {
            'live': {h['key']: reliability([r for r in live if r['horizon'] == h['key']]) for h in horizons},
            'simulated': {h['key']: reliability([r for r in simulated if r['horizon'] == h['key']])
                          for h in horizons},
        }

        latest = self.latest_analysis()
        ranking = {r['symbol']: r for r in (latest or {}).get('rankings', [])}
        live_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        simulated_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        for r in live:
            live_by_symbol.setdefault(r['symbol'], []).append(r)
        for r in simulated:
            simulated_by_symbol.setdefault(r['symbol'], []).append(r)
        assets: Dict[str, Dict[str, Any]] = {}
        for f in batch['forecasts']:
            entry = assets.get(f['symbol'])
            if entry is None:
                ranked = ranking.get(f['symbol'], {})
                own = live_by_symbol.get(f['symbol']) or simulated_by_symbol.get(f['symbol'], [])
                entry = assets[f['symbol']] = {
                    'symbol': f['symbol'],
                    'name': ranked.get('company_name') or (self.pipeline.asset_metadata(f['symbol'], None)['name']
                                                          if self.universe == 'crypto' else f['symbol']),
                    'sector': ranked.get('sector'),
                    'price': f['base_price'], 'base_date': f['base_date'],
                    'beat_probability': ranked.get('ml_probability'), 'rank': ranked.get('rank'),
                    'picked': ranked.get('picked', False),
                    'reliability_source': 'live' if any(not r['simulated'] for r in own) else 'simulated',
                    'reliability': {h['key']: reliability([r for r in own if r['horizon'] == h['key']])
                                    for h in horizons},
                }
            entry[f['horizon']] = {k: f.get(k) for k in ('q05', 'q15', 'q25', 'q50', 'q75', 'q85', 'q95', 'days', 'sigma')}
        return to_jsonable({
            'created_at': batch['created_at'], 'base_date': batch['base_date'], 'method': summary.get('method'),
            'horizons': horizons, 'evaluation': summary.get('evaluation', {}), 'reliability': overall,
            'assets': sorted(assets.values(), key=lambda a: (a['rank'] is None, a['rank'] or 0, a['symbol'])),
        })

    # ------------------------------------------------------------ portfolio

    @property
    def risk_rules(self) -> Dict[str, Any]:
        return {**DEFAULT_RULES, **(self.pipeline.universe_config.get('risk') or {})}

    def add_transaction(self, symbol: str, side: str, trade_date: str, quantity: float, price: float,
                        fees: float = 0.0, note: Optional[str] = None) -> Dict[str, Any]:
        """
        Record a trade after checking it against the history (a sale cannot
        exceed what was held on its date).

        Raises:
            TransactionError: the trade would make a holding negative
        """
        candidate = {'symbol': symbol, 'side': side, 'trade_date': trade_date, 'quantity': quantity,
                     'price': price, 'fees': fees, 'created_at': '9999', 'id': 'new'}
        apply_transactions([*self.store.list_transactions(self.universe), candidate])
        return self.store.add_transaction(self.universe, symbol, side, trade_date, quantity, price, fees, note)

    def delete_transaction(self, transaction_id: str) -> bool:
        """Remove a trade, unless a later sale depends on it."""
        remaining = [t for t in self.store.list_transactions(self.universe) if t['id'] != transaction_id]
        apply_transactions(remaining)
        return self.store.delete_transaction(self.universe, transaction_id)

    def _closes_since(self, symbols: List[str], start: str) -> Dict[str, pd.Series]:
        """Daily closes for these symbols from ``start``: the latest analysis's data when it covers them."""
        begin = pd.Timestamp(start)
        closes: Dict[str, pd.Series] = {}
        for s in symbols:
            data = self.prepared.get(s)
            if data is not None and 'Close' in data and len(data) and data.index[0] <= begin:
                closes[s] = data['Close']
        missing = [s for s in symbols if s not in closes]
        if missing:
            days = (pd.Timestamp.now().normalize() - begin).days
            period = next(p for limit, p in ((150, '6mo'), (330, '1y'), (700, '2y'), (10 ** 9, '5y')) if days <= limit)
            raw = self.pipeline.data_collector.fetch_multiple_stocks(missing, period=period)
            closes.update({s: d['Close'] for s, d in raw.items() if d is not None and not d.empty})
        return closes

    def _benchmark(self, start: str) -> Optional[pd.Series]:
        """The comparison for your portfolio: Bitcoin for crypto, the average asset of the list for stocks."""
        if self.universe == 'crypto':
            btc = self._closes_since(['BTC-USD'], start).get('BTC-USD')
            return btc / btc.dropna().iloc[0] if btc is not None and len(btc.dropna()) else None
        closes = self._closes(self.prepared or None)
        if not closes:
            return None
        returns = pd.DataFrame({s: c.pct_change() for s, c in closes.items()})
        average = returns[returns.index >= pd.Timestamp(start) - pd.Timedelta(days=7)].mean(axis=1).fillna(0.0)
        return (1 + average).cumprod()

    def portfolio_view(self) -> Dict[str, Any]:
        """Your holdings, gains, history against the benchmark, risk and warnings."""
        rules = self.risk_rules
        txs = self.store.list_transactions(self.universe)
        benchmark_label = 'Bitcoin' if self.universe == 'crypto' else f'the average stock of the {len(self.pipeline.symbols)} in the list'
        base = {'universe': self.universe, 'rules': rules, 'benchmark_label': benchmark_label,
                'transactions': to_jsonable(list(reversed(txs))), 'symbols': self.pipeline.symbols}
        if not txs:
            return {**base, 'empty': True, 'positions': [], 'warnings': [], 'history': [], 'sectors': [], 'summary': None}

        holdings = apply_transactions(txs)
        start = min(t['trade_date'] for t in txs)
        closes = self._closes_since(sorted(holdings), start)
        latest = self.latest_analysis()
        ranked = {r['symbol']: r for r in (latest or {}).get('rankings', [])}
        universe_size = len(ranked) or None
        batch = self.store.latest_forecast_batch(self.universe)
        week_key = 'week'
        ranges = {f['symbol']: f for f in (batch or {}).get('forecasts', []) if f['horizon'] == week_key}

        positions = []
        for symbol, h in sorted(holdings.items()):
            series = closes.get(symbol)
            price = float(series.dropna().iloc[-1]) if series is not None and len(series.dropna()) else None
            value = h.quantity * price if price is not None else None
            r = ranked.get(symbol, {})
            rng = ranges.get(symbol)
            positions.append({
                'symbol': symbol,
                'name': r.get('company_name') or (self.pipeline.asset_metadata(symbol, None)['name']
                                                  if self.universe == 'crypto' else symbol),
                'sector': r.get('sector') or (self.pipeline.asset_metadata(symbol, None)['sector']
                                              if self.universe == 'crypto' else None),
                'quantity': h.quantity, 'average_cost': h.average_cost, 'price': price, 'value': value,
                'cost_basis': h.cost_basis,
                'unrealized': (value - h.cost_basis) if value is not None and h.quantity > 0 else 0.0,
                'unrealized_pct': (value / h.cost_basis - 1) if value is not None and h.cost_basis > 0 else None,
                'realized': h.realized, 'fees': h.fees, 'first_date': h.first_date, 'trades': h.trades,
                'rank': r.get('rank'), 'universe_size': universe_size, 'score': r.get('composite_score'),
                'beat_probability': r.get('ml_probability'), 'picked': bool(r.get('picked')),
                'vol_forecast': r.get('vol_forecast'), 'vol_up_probability': r.get('vol_up_probability'),
                'week_range': {'low': rng['q05'], 'high': rng['q95'], 'days': rng['days']} if rng else None,
            })
        held = [p for p in positions if p['quantity'] > 0]
        total = sum(p['value'] or 0.0 for p in held)
        for p in positions:
            p['weight'] = (p['value'] or 0.0) / total if total > 0 and p['quantity'] > 0 else 0.0

        weights = {p['symbol']: p['weight'] for p in held}
        volatility = portfolio_volatility(weights, closes, periods_per_year=self.pipeline.periods_per_year)
        history = value_history(txs, closes, self._benchmark(start))
        invested = float(history['invested'].iloc[-1]) if len(history) else None
        bought = sum(t['quantity'] * t['price'] + (t.get('fees') or 0.0) for t in txs if t['side'] == 'buy')
        realized = sum(p['realized'] for p in positions)
        unrealized = sum(p['unrealized'] for p in held)
        benchmark_value = float(history['benchmark_value'].iloc[-1]) \
            if 'benchmark_value' in history and len(history) and pd.notna(history['benchmark_value'].iloc[-1]) else None
        sectors: Dict[str, float] = {}
        for p in held:
            sectors[p['sector'] or 'Unknown'] = sectors.get(p['sector'] or 'Unknown', 0.0) + p['weight']
        week_days = 7 if self.universe == 'crypto' else 5
        summary = {
            'value': total, 'invested': invested, 'bought': bought,
            'gain': unrealized + realized, 'unrealized': unrealized, 'realized': realized,
            'gain_pct': (unrealized + realized) / bought if bought > 0 else None,
            'benchmark_value': benchmark_value,
            'vs_benchmark': total - benchmark_value if benchmark_value is not None else None,
            'volatility': volatility, 'risk_label': risk_label(volatility),
            'next_week': weekly_range(total, volatility, week_days, self.pipeline.periods_per_year),
            'positions': len(held), 'as_of': max((str(c.dropna().index[-1].date()) for c in closes.values()
                                                  if len(c.dropna())), default=None),
            'since': start,
        }
        warnings = risk_warnings(held, volatility, rules, sectors=self.universe == 'stocks')
        step = max(1, len(history) // 400)  # keep the chart light
        points = history.iloc[::step]
        if len(history) and points.index[-1] != history.index[-1]:
            points = pd.concat([points, history.iloc[[-1]]])
        return to_jsonable({
            **base, 'empty': False, 'summary': summary, 'positions': positions, 'warnings': warnings,
            'sectors': [{'sector': k, 'weight': v} for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])],
            'history': [{'date': str(d.date()), 'value': float(r['value']), 'invested': float(r['invested']),
                         'benchmark': float(r['benchmark_value']) if 'benchmark_value' in r and pd.notna(r['benchmark_value']) else None}
                        for d, r in points.iterrows()],
        })

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

    def brief(self) -> Dict[str, Any]:
        """The weekly brief: the market, your portfolio, the model, ideas, alerts and what to do."""
        crypto = self.universe == 'crypto'
        days = 7 if crypto else 5
        period = 'week'
        noun = 'coins' if crypto else 'stocks'
        closes = self._closes(self.prepared or None)
        analysis = self.latest_analysis()
        names = {r['symbol']: r['symbol'] for r in (analysis or {}).get('rankings', [])}
        as_of = max((str(c.dropna().index[-1].date()) for c in closes.values() if len(c.dropna())), default=None)

        market = brief_rules.market_section(closes, days, names, noun, period)
        portfolio = self.portfolio_view()
        mine = brief_rules.portfolio_section(portfolio, days if crypto else 7, period)
        quality = (analysis or {}).get('summary', {}).get('model_quality', {}) if analysis else {}
        model = brief_rules.model_section(self.track_record(), quality, self.pipeline.horizon)
        batch = self.store.latest_forecast_batch(self.universe)
        ranges = {f['symbol']: f for f in (batch or {}).get('forecasts', []) if f['horizon'] == 'week'}
        ideas = brief_rules.ideas_section(analysis, ranges, model['facts']['proven'], long_term=self.long_term_view())
        since = str((pd.Timestamp(as_of) - pd.Timedelta(days=7)).date()) if as_of else None
        alerts = [a for a in self.notifier.store.list(self.universe, limit=200)
                  if since is None or a['event_date'] >= since]
        held = [p['symbol'] for p in portfolio.get('positions', []) if p['quantity'] > 0]
        alert_section = brief_rules.alerts_section(alerts, held)
        age = None
        if analysis:
            age = (pd.Timestamp.now().normalize() - pd.Timestamp(analysis['run']['data_date'])).days
        todo = brief_rules.actions(mine and portfolio, model, age, alert_section)
        sections = [s for s in (market, mine, model, ideas, alert_section) if s]
        result = {
            'universe': self.universe, 'as_of': as_of,
            'title': f"{self.pipeline.label}: your week in two minutes",
            'subtitle': f"Prices up to {brief_rules.nice_date(as_of)}." + (' Simulated demo prices.' if self.settings.demo_mode else ''),
            'sections': sections, 'actions': todo,
        }
        return to_jsonable(result)

    def brief_markdown(self) -> str:
        return brief_rules.to_markdown(self.brief())

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

        counted = [r for r in runs if not r.get('superseded')]
        live = [r for r in counted if not r['simulated']]
        simulated = [r for r in counted if r['simulated']]
        return {'live': summarize(live), 'simulated': summarize(simulated), 'runs': to_jsonable(runs),
                'superseded': sum(1 for r in runs if r.get('superseded') and not r['simulated'])}

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

    def asset_forecast(self, symbol: str) -> Optional[Dict[str, Any]]:
        view = self.forecast_view()
        if not view:
            return None
        asset = next((a for a in view['assets'] if a['symbol'] == symbol), None)
        if asset is None:
            return None
        return {'horizons': view['horizons'], 'base_date': view['base_date'], **asset}

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
            if run['simulated'] or not run['evaluated_at'] or run.get('superseded'):
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
        if job:
            job.message = 'Replaying price ranges on past dates'
        try:
            self.backfill_forecasts(self.prepared)
        except Exception as e:
            logger.warning(f'Could not replay {self.universe} forecasts: {e}')
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
