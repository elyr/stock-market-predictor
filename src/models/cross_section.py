"""
Cross-sectional ranking model.

Each day, compare the assets with each other and predict which will beat the
others over the next ``horizon`` days. Every choice below exists to keep a
small signal from being drowned by noise:

**Residual returns.** Each asset's daily log return minus beta times the
market's (the universe average for stocks, Bitcoin for crypto), with a
120-day rolling beta. The market's move is shared by every asset, so no
asset's own history can rank it.

**Ten features with a known reason to work**, computed from data up to and
including date t:

==============  ====================================================  =======================================
Feature         Formula                                                Rationale
==============  ====================================================  =======================================
rev_1d          −residual return today ÷ σ₆₀                           short-term overreaction reverses
rev_5d          −5-day residual return ÷ (σ₆₀ √5)                      weekly reversal
mom_12_1        log(P[t−21] ÷ P[t−252])           (stocks)             12-month momentum, skipping a month
mom_30, mom_90  log(P[t] ÷ P[t−30]), log(P[t] ÷ P[t−90])   (crypto)    crypto trends over weeks
low_vol         −60-day volatility                                     low-volatility anomaly
low_beta        −120-day beta                                          betting-against-beta
z_ma20          −(P ÷ 20-day mean − 1) ÷ (σ₂₀ √20)                     stretched prices pull back
high52          P ÷ 1-year high                                        52-week-high anchoring
max_ret         −largest daily return over 21 days                     lottery-like assets disappoint
vol_shock       log(volume ÷ 20-day mean volume)                       attention, news
rev_x_vol       raw rev_1d × −vol_shock                                quiet moves reverse, loud ones less so
==============  ====================================================  =======================================

σ₆₀ is the 60-day volatility of residual returns.

**Per-date normalisation.** On each date every feature is turned into its rank
among the assets and mapped onto a standard normal curve (ranks clipped to
1–99%). That makes the features comparable across calm and turbulent periods,
makes outliers harmless, and makes the model compare assets with each other
rather than with the past. Missing values become 0, the average.

**Target.** The asset's return over the horizon minus the universe average,
divided by its residual volatility, ranked per date onto the normal curve.
A regression on that, not a classification of "up or down", so large wins and
losses count for more than coin flips around zero.

**Models.** A ridge regression (heavily regularised, each date weighted
equally) is the default; a shallow XGBoost regressor can run beside it. A
logistic calibrator maps the score to the probability of beating the
universe, measured on a purged chronological hold-out.

The prepared frames carry the features as ``XS_*`` columns and the target as
``Target_XS``, so a single row can be scored without the rest of the universe.
"""

import copy
import logging
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score

from src.models.ml_models import (chronological_split, information_coefficient, reliability_table)

logger = logging.getLogger(__name__)

PREFIX = 'XS_'
TARGET = 'Target_XS'
OUTCOME = 'Target_Up_Rel'      # beat the universe (0/1), for accuracy and calibration
RETURN = 'Future_Excess'       # return minus the universe average, for the IC

BETA_WINDOW = 120
VOL_WINDOW = 60
RANK_CLIP = 0.01

FEATURE_LABELS = {
    'XS_rev_1d': "Reversal of today's move",
    'XS_rev_5d': 'Reversal of the last 5 days',
    'XS_mom_12_1': '12-month momentum (skipping the last month)',
    'XS_mom_30': '30-day momentum',
    'XS_mom_90': '90-day momentum',
    'XS_low_vol': 'Low volatility',
    'XS_low_beta': 'Low beta',
    'XS_z_ma20': 'Below its 20-day average',
    'XS_high52': 'Close to its 1-year high',
    'XS_max_ret': 'No lottery-like jumps',
    'XS_vol_shock': 'Unusual volume',
    'XS_rev_x_vol': 'Reversal of a quiet move',
}

DEFAULT_CONFIG = {
    'model': 'cross_section',
    'cross_section': {
        'ridge': {'enabled': True, 'alpha': 1000.0},
        'xgboost': {'enabled': False, 'n_estimators': 300, 'max_depth': 2, 'learning_rate': 0.03,
                    'min_child_weight': 200, 'subsample': 0.7, 'colsample_bytree': 0.7, 'random_state': 42},
    },
    'training': {'target': 'relative', 'horizon': 5, 'test_size': 0.2, 'min_samples': 200, 'calibrate': True},
}


# --------------------------------------------------------------------- features

def gaussian_rank(panel: pd.DataFrame) -> pd.DataFrame:
    """Rank each row (date) across columns (assets) and map onto a standard normal; NaN stays NaN."""
    panel = panel.replace([np.inf, -np.inf], np.nan)
    counts = panel.notna().sum(axis=1)
    pct = (panel.rank(axis=1) - 0.5).div(counts.replace(0, np.nan), axis=0)
    ranked = pd.DataFrame(norm.ppf(pct.clip(RANK_CLIP, 1 - RANK_CLIP)), index=panel.index, columns=panel.columns)
    return ranked.where(counts.ge(3), np.nan, axis=0) if len(ranked) else ranked


def _panel(prepared: Dict[str, pd.DataFrame], column: str) -> pd.DataFrame:
    return pd.concat({s: d[column] for s, d in prepared.items() if column in d}, axis=1).sort_index()


def raw_features(close: pd.DataFrame, volume: pd.DataFrame, market: Optional[str] = None,
                 momentum: str = 'long', year: int = 252) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
    """
    Unranked feature panels (dates × assets) from closing prices and volumes.

    Args:
        close, volume: dates × assets
        market: asset whose return is the market factor (e.g. 'BTC-USD'); None = universe average
        momentum: 'long' (12-month, skipping a month) or 'short' (30 and 90 days)
        year: rows in a year (252 trading days, 365 calendar days)

    Returns:
        (feature name -> panel, 60-day residual volatility panel)
    """
    r = np.log(close).diff()
    m = r[market] if market and market in r else r.mean(axis=1)
    var = m.rolling(BETA_WINDOW, min_periods=BETA_WINDOW // 2).var()
    beta = r.apply(lambda col: col.rolling(BETA_WINDOW, min_periods=BETA_WINDOW // 2).cov(m)).div(var, axis=0)
    residual = r - beta.fillna(1.0).mul(m, axis=0)
    sigma = residual.rolling(VOL_WINDOW, min_periods=20).std()
    shock = np.log(volume.where(volume > 0) / volume.rolling(20, min_periods=10).mean())
    rev_1d = -residual / sigma

    features = {
        'rev_1d': rev_1d,
        'rev_5d': -residual.rolling(5).sum() / (sigma * np.sqrt(5)),
        'low_vol': -r.rolling(VOL_WINDOW, min_periods=20).std(),
        'low_beta': -beta,
        'z_ma20': -(close / close.rolling(20).mean() - 1) / (r.rolling(20).std() * np.sqrt(20)),
        'high52': close / close.rolling(year, min_periods=60).max(),
        'max_ret': -r.rolling(21).max(),
        'vol_shock': shock,
        'rev_x_vol': rev_1d * -shock,
    }
    if momentum == 'short':
        features['mom_30'] = np.log(close / close.shift(30))
        features['mom_90'] = np.log(close / close.shift(90))
    else:
        features['mom_12_1'] = np.log(close.shift(21) / close.shift(year))
    return {k: v.replace([np.inf, -np.inf], np.nan) for k, v in features.items()}, sigma


def add_cross_section_features(prepared: Dict[str, pd.DataFrame], horizon: int, market: Optional[str] = None,
                               momentum: str = 'long', year: int = 252) -> Dict[str, pd.DataFrame]:
    """
    Add the ranked ``XS_*`` features and the ``Target_XS`` target to every prepared frame.

    Needs ``Close`` and ``Volume`` and, for the target, ``Future_Excess`` (see
    :func:`src.data.preprocessor.add_relative_targets`).
    """
    if len(prepared) < 3:
        return prepared
    close, volume = _panel(prepared, 'Close'), _panel(prepared, 'Volume')
    features, sigma = raw_features(close, volume, market=market, momentum=momentum, year=year)
    ranked = {PREFIX + name: gaussian_rank(panel) for name, panel in features.items()}
    target = None
    if all(RETURN in d for d in prepared.values()):
        excess = _panel(prepared, RETURN)
        target = gaussian_rank(excess / (sigma * np.sqrt(horizon)))

    result = {}
    for symbol, data in prepared.items():
        df = data.copy()
        for name, panel in ranked.items():
            df[name] = panel[symbol].reindex(df.index)
        if target is not None:
            df[TARGET] = target[symbol].reindex(df.index)
        result[symbol] = df
    return result


def feature_label(name: str) -> str:
    return FEATURE_LABELS.get(name, name.replace(PREFIX, '').replace('_', ' '))


# ------------------------------------------------------------------------ model

def _merge(base: Dict, override: Dict) -> Dict:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        result[key] = _merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) \
            else copy.deepcopy(value)
    return result


class CrossSectionPredictor:
    """
    Ridge (and optionally XGBoost) on per-date ranked features; same interface as
    :class:`src.models.ml_models.StockPredictor` where the pipeline uses it.
    """

    kind = 'cross_section'

    def __init__(self, config: Optional[Dict] = None):
        self.config = _merge(DEFAULT_CONFIG, config or {})
        self.models: Dict[str, Any] = {}
        self.scalers: Dict[str, Any] = {}
        self.calibrator: Optional[LogisticRegression] = None
        self.feature_columns: List[str] = []
        self.feature_importance: Dict[str, Dict[str, float]] = {}
        self.model_performance: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------ properties

    @property
    def horizon(self) -> int:
        return int(self.config['training'].get('horizon', 5))

    @property
    def target_column(self) -> str:
        return TARGET

    @property
    def return_column(self) -> str:
        return RETURN

    # ------------------------------------------------------------- training

    def _frame(self, data: pd.DataFrame) -> pd.DataFrame:
        if TARGET not in data.columns:
            raise ValueError(f"{TARGET} missing; prepare the data with the cross-sectional features")
        return data.dropna(subset=[TARGET]).sort_index(kind='stable')

    def _matrix(self, data: pd.DataFrame) -> pd.DataFrame:
        return data.reindex(columns=self.feature_columns).astype(float).fillna(0.0)

    @staticmethod
    def _date_weights(index: pd.Index) -> np.ndarray:
        """Each date counts once, however many assets it has."""
        counts = pd.Series(1, index=index).groupby(level=0).transform('size')
        return (1.0 / counts).to_numpy()

    def _fit(self, frame: pd.DataFrame) -> None:
        X, y, w = self._matrix(frame), frame[TARGET].to_numpy(), self._date_weights(frame.index)
        settings = self.config['cross_section']
        self.models = {}
        if settings['ridge'].get('enabled', True):
            self.models['ridge'] = Ridge(alpha=float(settings['ridge'].get('alpha', 1000.0))).fit(X, y, sample_weight=w)
        if settings['xgboost'].get('enabled', False):
            from xgboost import XGBRegressor
            params = {k: v for k, v in settings['xgboost'].items() if k != 'enabled'}
            self.models['xgboost'] = XGBRegressor(verbosity=0, **params).fit(X, y, sample_weight=w * len(w) / w.sum())
        if not self.models:
            raise ValueError("No cross-sectional model is enabled")
        self.feature_importance = {}
        for name, model in self.models.items():
            values = np.abs(model.coef_) if name == 'ridge' else model.feature_importances_
            self.feature_importance[name] = dict(zip(self.feature_columns, map(float, values)))

    def _scores(self, X: pd.DataFrame) -> Dict[str, np.ndarray]:
        return {name: np.asarray(model.predict(X), dtype=float) for name, model in self.models.items()}

    def train_all_models(self, data: pd.DataFrame, test_size: Optional[float] = None,
                         cross_validate: Optional[bool] = None) -> Dict[str, Dict[str, Any]]:
        """Fit on the older dates and score the hold-out (``test_size=0`` fits on everything)."""
        frame = self._frame(data)
        if len(frame) < self.config['training']['min_samples']:
            raise ValueError(f"Insufficient data for training ({len(frame)} rows, "
                             f"minimum {self.config['training']['min_samples']} required)")
        self.feature_columns = sorted(c for c in frame.columns if c.startswith(PREFIX))
        if not self.feature_columns:
            raise ValueError("No cross-sectional features found")
        test_size = self.config['training']['test_size'] if test_size is None else test_size
        train, test = chronological_split(frame.index, test_size, purge_days=self.horizon)
        self._fit(frame[train])
        performance: Dict[str, Dict[str, Any]] = {}
        if not test.any():
            return performance
        held_out = frame[test]
        outcome = held_out[OUTCOME].astype(int).to_numpy() if OUTCOME in held_out else None
        for name, score in self._scores(self._matrix(held_out)).items():
            entry = {'scores': score, **information_coefficient(score, held_out[RETURN], held_out.index)}
            if outcome is not None and len(np.unique(outcome)) > 1:
                entry['test_accuracy'] = float(accuracy_score(outcome, (score > 0).astype(int)))
                entry['test_auc'] = float(roc_auc_score(outcome, score))
            performance[name] = entry
        logger.info(f"Cross-sectional model: {int(train.sum())} training rows, {int(test.sum())} test rows, "
                    f"{len(self.feature_columns)} features")
        return performance

    def train_evaluate_and_refit(self, data: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """Measure quality on a purged hold-out, fit the probability calibrator there, then refit on everything."""
        self.calibrator = None
        performance = self.train_all_models(data)
        if performance:
            frame = self._frame(data)
            _, test = chronological_split(frame.index, self.config['training']['test_size'], self.horizon)
            held_out = frame[test]
            score = np.mean([p['scores'] for p in performance.values()], axis=0)
            outcome = held_out[OUTCOME].astype(int).to_numpy()
            two_classes = len(np.unique(outcome)) > 1
            if self.config['training'].get('calibrate', True) and two_classes:
                self.calibrator = LogisticRegression(C=1.0).fit(score.reshape(-1, 1), outcome)
            probability = self._probability(score)
            performance['ensemble'] = {
                'test_accuracy': float(accuracy_score(outcome, (probability > 0.5).astype(int))),
                'test_auc': float(roc_auc_score(outcome, score)) if two_classes else None,
                'test_base_rate': float(outcome.mean()),
                'brier_raw': float(brier_score_loss(outcome, norm.cdf(score))),
                'brier_calibrated': float(brier_score_loss(outcome, probability)),
                'reliability': reliability_table(probability, outcome),
                'test_rows': int(len(held_out)),
                'test_start': str(held_out.index.min().date()),
                'test_end': str(held_out.index.max().date()),
                **information_coefficient(score, held_out[RETURN], held_out.index),
            }
            for entry in performance.values():
                entry.pop('scores', None)
        calibrator = self.calibrator
        self.train_all_models(data, test_size=0)
        self.calibrator = calibrator
        self.model_performance = performance
        return performance

    # ----------------------------------------------------------- prediction

    def _probability(self, score: np.ndarray) -> np.ndarray:
        """Probability of beating the universe; without a calibrator, the target's normal scale."""
        if self.calibrator is not None:
            return self.calibrator.predict_proba(np.asarray(score).reshape(-1, 1))[:, 1]
        return norm.cdf(score)

    def predict(self, data: pd.DataFrame, model_name: str = 'ensemble') -> Dict[str, Any]:
        """Scores and probabilities for each row (same keys as StockPredictor.predict)."""
        if not self.models:
            raise ValueError("No trained models available. Train models first.")
        scores = self._scores(self._matrix(data))
        if model_name != 'ensemble':
            if model_name not in scores:
                raise ValueError(f"Model {model_name} not found")
            scores = {model_name: scores[model_name]}
        raw = np.mean(list(scores.values()), axis=0)
        probabilities = self._probability(raw)
        return {
            'predictions': (probabilities > 0.5).astype(int),
            'probabilities': probabilities,
            'raw_probabilities': norm.cdf(raw),
            'scores': raw,
            'individual_probabilities': {k: norm.cdf(v) for k, v in scores.items()},
            'individual_predictions': {k: (v > 0).astype(int) for k, v in scores.items()},
        }

    def explain(self, row: pd.DataFrame, top_n: int = 6) -> List[Dict[str, Any]]:
        """The ridge model's contributions (weight × ranked value) for one row, largest first."""
        model = self.models.get('ridge')
        if model is None or row.empty:
            return []
        values = self._matrix(row.tail(1)).iloc[0]
        contributions = model.coef_ * values.to_numpy()
        order = np.argsort(-np.abs(contributions))[:top_n]
        return [{
            'feature': self.feature_columns[i],
            'label': feature_label(self.feature_columns[i]),
            'value': float(values.iloc[i]),
            'contribution': float(contributions[i]),
        } for i in order if contributions[i] != 0]

    def coefficients(self) -> Dict[str, float]:
        """The ridge model's signed weights per feature (what the model learned points up or down)."""
        model = self.models.get('ridge')
        return dict(zip(self.feature_columns, map(float, model.coef_))) if model is not None else {}

    def get_feature_importance(self, model_name: str = 'ridge', top_n: int = 20) -> List[Tuple[str, float]]:
        importance = self.feature_importance.get(model_name) \
            or next(iter(self.feature_importance.values()), {})
        return sorted(importance.items(), key=lambda x: x[1], reverse=True)[:top_n]

    # ---------------------------------------------------------- persistence

    def save_models(self, filepath: str) -> None:
        joblib.dump({'kind': self.kind, 'models': self.models, 'calibrator': self.calibrator,
                     'feature_columns': self.feature_columns, 'feature_importance': self.feature_importance,
                     'model_performance': self.model_performance, 'config': self.config}, filepath)

    def load_models(self, filepath: str) -> None:
        state = joblib.load(filepath)
        self.models, self.calibrator = state['models'], state.get('calibrator')
        self.feature_columns, self.feature_importance = state['feature_columns'], state['feature_importance']
        self.model_performance, self.config = state['model_performance'], state['config']


def make_predictor(ml_config: Optional[Dict] = None, kind: Optional[str] = None):
    """The return model the settings ask for: ``cross_section`` (default) or ``legacy``."""
    ml_config = ml_config or {}
    kind = kind or ml_config.get('model', 'cross_section')
    if kind == 'legacy':
        from src.models.ml_models import StockPredictor
        predictor = StockPredictor(ml_config)
        predictor.kind = 'legacy'
        return predictor
    if kind != 'cross_section':
        raise ValueError(f"Unknown model '{kind}'; expected 'cross_section' or 'legacy'")
    return CrossSectionPredictor(ml_config)
