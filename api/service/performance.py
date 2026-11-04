"""
Backtests, predicted vs actual, and experiments with the locked period.

Part of :class:`api.service.UniverseService`; methods use the shared
state set up in ``core.py`` (pipeline, store, settings).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from api.jobs import Job
from api.serialization import to_jsonable
from src.backtest import Backtester
from src.backtest.backtester import STRATEGY_LABELS
from src.evaluation import ExperimentRunner, build_report, normalize_log, validate_settings
from src.evaluation.comparator import LOG_COLUMNS


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

class PerformanceMixin:
    """Backtests, predicted vs actual, and experiments with the locked period."""

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
