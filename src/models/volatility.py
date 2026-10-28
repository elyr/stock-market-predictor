"""
Volatility forecasting.

Unlike the direction of returns, the *size* of moves is strongly predictable:
quiet periods follow quiet periods and turbulent periods follow turbulent ones
(volatility clustering). This module forecasts, for each asset:

* the probability that its realised volatility over the next ``horizon`` days
  exceeds its trailing 20-day volatility (classification), and
* the level of that future volatility (regression on log volatility).

Both models are pooled across the universe and evaluated on a purged
chronological hold-out against a naive baseline ("next period's volatility
equals the last 20 days'"), so the reported skill is relative to a sensible
default, not to nothing.
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import accuracy_score, r2_score, roc_auc_score

from src.models.ml_models import chronological_split, to_matrix

logger = logging.getLogger(__name__)

VOL_FEATURES = [
    'Volatility_5d', 'Volatility_20d', 'Volatility_60d', 'Vol_Ratio_5_20', 'Abs_Return',
    'Range_Pct', 'ATR_Pct', 'BB_Width_Pct', 'Volume_Ratio', 'ADX', 'ROC_5d', 'ROC_20d',
    'RSI', 'Gap_Size_Pct', 'Market_Vol_5d', 'Market_Vol_20d', 'Market_Return_5d',
]


def add_market_volatility(prepared: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Add universe-wide volatility and return features (cross-sectional averages per date)."""
    if not prepared:
        return prepared
    vol5 = pd.concat({s: d['Volatility_5d'] for s, d in prepared.items()}, axis=1).mean(axis=1)
    vol20 = pd.concat({s: d['Volatility_20d'] for s, d in prepared.items()}, axis=1).mean(axis=1)
    ret5 = pd.concat({s: d['ROC_5d'] for s, d in prepared.items()}, axis=1).mean(axis=1)
    result = {}
    for symbol, data in prepared.items():
        df = data.copy()
        df['Market_Vol_5d'] = vol5.reindex(df.index)
        df['Market_Vol_20d'] = vol20.reindex(df.index)
        df['Market_Return_5d'] = ret5.reindex(df.index)
        result[symbol] = df
    return result


class VolatilityForecaster:
    """Pooled volatility models for one universe."""

    def __init__(self, horizon: int = 5, periods_per_year: int = 252, test_size: float = 0.2):
        self.horizon = horizon
        self.periods_per_year = periods_per_year
        self.test_size = test_size
        self.classifier: Optional[HistGradientBoostingClassifier] = None
        self.regressor: Optional[HistGradientBoostingRegressor] = None
        self.features: List[str] = []
        self.performance: Dict[str, Any] = {}

    def _frame(self, pooled: pd.DataFrame) -> pd.DataFrame:
        frame = pooled.dropna(subset=['Target_Vol_Up', 'Future_Vol', 'Volatility_20d'])
        frame = frame[(frame['Future_Vol'] > 0) & (frame['Volatility_20d'] > 0)]
        return frame.sort_index(kind='stable')

    def fit(self, pooled: pd.DataFrame) -> Dict[str, Any]:
        """
        Evaluate on a purged hold-out, then refit on everything.

        Returns:
            Hold-out metrics: classification accuracy, base rate, AUC, and R² of
            the model vs the naive "same as last 20 days" forecast.
        """
        frame = self._frame(pooled)
        if len(frame) < 300:
            raise ValueError(f"Not enough rows for volatility models ({len(frame)})")
        self.features = [f for f in VOL_FEATURES if f in frame.columns]
        X = to_matrix(frame, self.features)
        y_cls = frame['Target_Vol_Up'].astype(int).values
        y_reg = np.log(frame['Future_Vol'].values)
        naive = np.log(frame['Volatility_20d'].values)

        train, test = chronological_split(frame.index, self.test_size, self.horizon)
        clf = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, random_state=42)
        reg = HistGradientBoostingRegressor(max_depth=4, max_iter=200, learning_rate=0.05, random_state=42)
        clf.fit(X[train], y_cls[train])
        reg.fit(X[train], y_reg[train])

        proba = clf.predict_proba(X[test])[:, 1]
        pred_reg = reg.predict(X[test])
        self.performance = {
            'accuracy': float(accuracy_score(y_cls[test], (proba > 0.5).astype(int))),
            'base_rate': float(max(y_cls[test].mean(), 1 - y_cls[test].mean())),
            'auc': float(roc_auc_score(y_cls[test], proba)) if len(np.unique(y_cls[test])) > 1 else None,
            'r2_model': float(r2_score(y_reg[test], pred_reg)),
            'r2_naive': float(r2_score(y_reg[test], naive[test])),
            'test_rows': int(test.sum()),
            'horizon': self.horizon,
        }
        logger.info(f"Volatility model: accuracy {self.performance['accuracy']:.3f} "
                    f"(majority {self.performance['base_rate']:.3f}), R² {self.performance['r2_model']:.3f} "
                    f"vs naive {self.performance['r2_naive']:.3f}")

        self.classifier = clf.fit(X, y_cls)
        self.regressor = reg.fit(X, y_reg)
        return self.performance

    def predict(self, latest: pd.DataFrame) -> pd.DataFrame:
        """
        Forecast for the latest row of each asset.

        Args:
            latest: one row per asset (index = symbols or dates), with feature columns

        Returns:
            DataFrame with prob_vol_up, current_vol and forecast_vol (both annualized)
        """
        if self.classifier is None:
            raise ValueError("Volatility models are not trained")
        X = to_matrix(latest, self.features)
        annualize = np.sqrt(self.periods_per_year)
        return pd.DataFrame({
            'prob_vol_up': self.classifier.predict_proba(X)[:, 1],
            'current_vol': latest['Volatility_20d'].values * annualize,
            'forecast_vol': np.exp(self.regressor.predict(X)) * annualize,
        }, index=latest.index)
