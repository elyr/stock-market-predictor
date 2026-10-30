"""
Experiments: compare settings fairly, without fooling yourself.

An experiment is a set of setting changes (model depth, horizon, score weights,
portfolio rules...) run through the same walk-forward backtest as the live
system. Every experiment is scored on the same **development period** and
reported through the predicted-versus-actual comparator, so experiments can be
compared side by side with the current settings.

The most recent ``lockbox_days`` are a **locked period**. Development runs never
make a decision whose outcome falls inside it. When you have picked a winner,
you check it once on the locked period. If its edge holds up there, it is more
likely to be real; if it vanishes, the "improvement" was probably fitted to the
development period's noise. Each experiment's locked-period result is computed
once and then only read back, so it cannot be re-run until it looks good.

Only settings in :data:`ALLOWED_SETTINGS` can be changed, which keeps
experiments to meaningful knobs and keeps API input safe.
"""

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.backtest import Backtester, BacktestResult
from src.evaluation.comparator import build_report, headline
from src.prediction import create_pipeline

# Gap between the end of the development period and the locked period, in
# rows. It is at least the longest allowed horizon, so no development decision
# has an outcome inside the locked period, and every experiment shares one
# development window whatever its horizon.
LOCKBOX_GAP = 20

ALLOWED_SETTINGS: Dict[str, Dict[str, Any]] = {
    'ml_config.model': {'type': 'choice', 'choices': ['cross_section', 'legacy'], 'label': 'Model'},
    'ml_config.cross_section.ridge.alpha': {'type': 'float', 'min': 1, 'max': 100000, 'label': 'Ridge shrinkage (alpha)'},
    'ml_config.cross_section.xgboost.enabled': {'type': 'bool', 'label': 'Add the XGBoost challenger'},
    'ml_config.cross_section.xgboost.max_depth': {'type': 'int', 'min': 1, 'max': 6, 'label': 'Challenger depth'},
    'ml_config.training.horizon': {'type': 'int', 'min': 1, 'max': 20, 'label': 'Prediction horizon (days)'},
    'ml_config.training.target': {'type': 'choice', 'choices': ['relative', 'absolute'], 'label': 'Target'},
    'ml_config.models.xgboost.max_depth': {'type': 'int', 'min': 1, 'max': 10, 'label': 'XGBoost depth'},
    'ml_config.models.xgboost.n_estimators': {'type': 'int', 'min': 20, 'max': 1000, 'label': 'XGBoost trees'},
    'ml_config.models.xgboost.learning_rate': {'type': 'float', 'min': 0.005, 'max': 0.5, 'label': 'XGBoost learning rate'},
    'ml_config.models.random_forest.max_depth': {'type': 'int', 'min': 1, 'max': 20, 'label': 'Random forest depth'},
    'ml_config.models.random_forest.min_samples_leaf': {'type': 'int', 'min': 1, 'max': 500, 'label': 'Random forest leaf size'},
    'ml_config.models.random_forest.enabled': {'type': 'bool', 'label': 'Use random forest'},
    'ml_config.models.xgboost.enabled': {'type': 'bool', 'label': 'Use XGBoost'},
    'ml_config.models.neural_network.enabled': {'type': 'bool', 'label': 'Use neural network'},
    'ranking_config.weights.ml_prediction': {'type': 'float', 'min': 0, 'max': 1, 'label': 'Weight: model'},
    'ranking_config.weights.technical_score': {'type': 'float', 'min': 0, 'max': 1, 'label': 'Weight: technical'},
    'ranking_config.weights.momentum_score': {'type': 'float', 'min': 0, 'max': 1, 'label': 'Weight: momentum'},
    'ranking_config.weights.volume_score': {'type': 'float', 'min': 0, 'max': 1, 'label': 'Weight: volume'},
    'portfolio.weighting': {'type': 'choice', 'choices': ['equal', 'inverse_volatility'], 'label': 'Position sizing'},
    'portfolio.max_per_sector': {'type': 'int', 'min': 0, 'max': 10, 'label': 'Max picks per sector (0 = no cap)'},
}


def validate_settings(universe: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check an experiment's settings and turn them into config overrides.

    Raises:
        ValueError: on an unknown setting or a value out of range
    """
    overrides: Dict[str, Any] = {}
    for key, value in (settings or {}).items():
        spec = ALLOWED_SETTINGS.get(key)
        if spec is None:
            raise ValueError(f"'{key}' cannot be changed in an experiment")
        kind = spec['type']
        try:
            if kind == 'int':
                value = int(value)
            elif kind == 'float':
                value = float(value)
            elif kind == 'bool':
                if not isinstance(value, bool):
                    raise ValueError
            elif kind == 'choice' and value not in spec['choices']:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"Invalid value for '{key}': {value!r}")
        if kind in ('int', 'float') and not spec['min'] <= value <= spec['max']:
            raise ValueError(f"'{key}' must be between {spec['min']} and {spec['max']}")
        path = f"universes.{universe}.{key}" if key.startswith('portfolio.') else key
        overrides[path] = value
    model_flags = [k for k in ('random_forest', 'xgboost', 'neural_network')
                   if settings.get(f'ml_config.models.{k}.enabled') is False]
    if len(model_flags) == 3:
        raise ValueError('At least one model must stay enabled')
    return overrides


def split_periods(calendar: pd.DatetimeIndex, horizon: int, lockbox_days: int,
                  test_days: int) -> Dict[str, Optional[pd.Timestamp]]:
    """
    Development and locked windows on a price calendar.

    The windows are anchored to the calendar, not to the horizon, so every
    experiment is judged on exactly the same dates. The locked period is the
    last ``lockbox_days`` rows (its last decisions are ``horizon`` rows before
    the end, so their outcomes are known). Development ends ``LOCKBOX_GAP`` rows
    before the locked period starts, which is at least the longest horizon, so
    no development outcome falls inside the locked period.
    """
    if len(calendar) < lockbox_days + LOCKBOX_GAP + 30:
        raise ValueError('Not enough history to set aside a locked period')
    lockbox_start = calendar[-lockbox_days]
    dev_end = calendar[-lockbox_days - LOCKBOX_GAP]
    dev_dates = calendar[calendar <= dev_end][-test_days:]
    return {'dev_start': dev_dates[0], 'dev_end': dev_end, 'lockbox_start': lockbox_start,
            'lockbox_end': calendar[-1 - max(horizon, 1)]}


def summarize_run(result: BacktestResult) -> Dict[str, Any]:
    """Comparator report plus the backtest's return figures, for one run."""
    report = build_report(result.predictions)
    metrics = result.metrics
    composite = metrics.loc['Composite after costs'] if 'Composite after costs' in metrics.index else None
    return {
        'report': report,
        'headline': {
            **headline(report),
            'annualized_return': float(composite['annualized_return']) if composite is not None else None,
            'excess_t_stat': float(composite['excess_t_stat']) if composite is not None and pd.notna(composite['excess_t_stat']) else None,
            'universe_annualized_return': float(metrics.loc['Equal-weight universe', 'annualized_return'])
            if 'Equal-weight universe' in metrics.index else None,
        },
    }


class ExperimentRunner:
    """
    Runs experiments for one universe.

    Args:
        universe: 'stocks' or 'crypto'
        config_path: base config file (experiments override parts of it)
        data_collector: data source shared with the live pipeline
        lockbox_days: length of the locked period
        test_days: length of the development period
    """

    def __init__(self, universe: str, config_path: str, data_collector=None,
                 lockbox_days: int = 60, test_days: int = 250, symbols: Optional[List[str]] = None):
        self.universe = universe
        self.config_path = config_path
        self.data_collector = data_collector
        self.lockbox_days = lockbox_days
        self.test_days = test_days
        self.symbols = symbols

    def _pipeline(self, overrides: Dict[str, Any]):
        return create_pipeline(self.universe, self.config_path, data_collector=self.data_collector,
                               config_overrides=overrides)

    def _prepare(self, overrides: Dict[str, Any]) -> Tuple[Any, Dict[str, pd.DataFrame], Dict[str, Any]]:
        pipeline = self._pipeline(overrides)
        period = pipeline.config.get('backtest', {}).get('period', '2y')
        prepared = pipeline.fetch_and_prepare_data(self.symbols or pipeline.symbols, period=period)
        calendar = pd.DatetimeIndex(sorted(set().union(*(d.index for d in prepared.values()))))
        windows = split_periods(calendar, pipeline.horizon, self.lockbox_days, self.test_days)
        return pipeline, prepared, windows

    def run_development(self, settings: Dict[str, Any], top_n: Optional[int] = None,
                        retrain_every: Optional[int] = None) -> Dict[str, Any]:
        """Run on the development period only (never looks at the locked period)."""
        overrides = validate_settings(self.universe, settings)
        pipeline, prepared, windows = self._prepare(overrides)
        tester = Backtester.from_config(pipeline, top_n=top_n, retrain_every=retrain_every,
                                        test_days=self.test_days, end_date=str(windows['dev_end'].date()))
        result = tester.run(prepared)
        return {'result': result, 'summary': summarize_run(result), 'windows': windows, 'overrides': overrides}

    def run_lockbox(self, settings: Dict[str, Any], top_n: Optional[int] = None,
                    retrain_every: Optional[int] = None) -> Dict[str, Any]:
        """Run on the locked period (to be done once per chosen experiment)."""
        overrides = validate_settings(self.universe, settings)
        pipeline, prepared, windows = self._prepare(overrides)
        tester = Backtester.from_config(pipeline, top_n=top_n, retrain_every=retrain_every,
                                        test_days=self.lockbox_days,
                                        start_date=str(windows['lockbox_start'].date()))
        result = tester.run(prepared)
        return {'result': result, 'summary': summarize_run(result), 'windows': windows, 'overrides': overrides}
