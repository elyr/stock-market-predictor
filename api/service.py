"""
Per-universe application service: runs analyses and backtests, records
predictions, scores them once their horizon has passed, and assembles the
data each dashboard page needs.

There is one ``UniverseService`` per asset class, each wrapping its own
pipeline (and therefore its own trained models).
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from api.jobs import Job
from api.serialization import snake_records, to_jsonable
from api.settings import Settings
from api.store import Store
from src.backtest import Backtester
from src.backtest.backtester import STRATEGY_LABELS
from src.data.synthetic import SyntheticDataCollector
from src.prediction import create_pipeline

logger = logging.getLogger(__name__)

HISTORY_COLUMNS = {
    'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume',
    'SMA_20': 'sma_20', 'SMA_50': 'sma_50', 'SMA_200': 'sma_200',
    'BB_Upper': 'bb_upper', 'BB_Lower': 'bb_lower', 'RSI': 'rsi',
    'MACD': 'macd', 'MACD_Signal': 'macd_signal', 'Volatility_20d': 'volatility_20d',
}


class UniverseService:
    def __init__(self, universe: str, settings: Settings, store: Store, collector=None):
        self.universe = universe
        self.settings = settings
        self.store = store
        if collector is None and settings.demo_mode:
            collector = SyntheticDataCollector(reversal=0.2)
        self.pipeline = create_pipeline(universe, settings.config_path, data_collector=collector)
        if settings.demo_mode:
            self.pipeline.use_sentiment = False
        self.prepared: Dict[str, pd.DataFrame] = {}

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
        if job:
            job.message = f'Fetching prices and training {self.pipeline.label} models'
        result = self.pipeline.get_top_10_recommendations(symbols or self.default_symbols(), top_n=top_n)
        rankings = result['full_rankings']
        if rankings.empty:
            raise RuntimeError('No assets passed the filters or no data was available')

        self.prepared = dict(self.pipeline.last_prepared)
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
        run_id = self.store.save_run(self.universe, summary['data_date'], self.pipeline.horizon,
                                     len(weights), summary, predictions, demo=self.settings.demo_mode)
        try:
            self.pipeline.save_models()
        except Exception as e:
            logger.warning(f"Could not save {self.universe} models: {e}")

        if job:
            job.message = 'Scoring earlier predictions that have matured'
        evaluated = self.evaluate_outcomes(self.prepared)
        return {'run_id': run_id, 'evaluated_runs': evaluated}

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
        payload = serialize_backtest(result)
        backtest_id = self.store.save_backtest(self.universe, {**params, 'symbols': len(symbols)}, payload,
                                               demo=self.settings.demo_mode)
        if record_simulated:
            self._record_simulated_runs(result)
        return {'backtest_id': backtest_id}

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
        return {**backtest, **analysis}


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
