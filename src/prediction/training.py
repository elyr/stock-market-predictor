"""
The models: training the next-week and long-term models, saving, exporting and importing them.

Part of :class:`src.prediction.asset_ranker.AssetRanker`; methods use the state
set up in its ``__init__`` (config, data collector, predictors).
"""

import logging
import os
from typing import Any, Dict, Optional

import joblib
import pandas as pd

from src.models.cross_section import feature_label as cross_section_label
from src.models.cross_section import make_long_predictor, make_predictor
from src.models.ml_models import feature_label as legacy_label
from src.models.registry import correct_overlap

logger = logging.getLogger(__name__)


def any_feature_label(name: str) -> str:
    """Readable name of a model input, from either model's labels."""
    return cross_section_label(name) if name.startswith('XS_') else legacy_label(name)


class TrainingMixin:
    """The models: training the next-week and long-term models, saving, exporting and importing them."""

    def new_predictor(self):
        """A fresh, untrained return model of the configured kind."""
        return make_predictor(self.config.get('ml_config', {}))

    @staticmethod
    def pool(prepared_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        frames = [data.assign(Symbol=symbol) for symbol, data in prepared_data.items()]
        return pd.concat(frames).sort_index(kind='stable') if frames else pd.DataFrame()

    def train_ml_models(self, prepared_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, Any]]:
        """
        Train this universe's return and volatility models on its pooled history.

        Returns:
            Return-model performances (empty if there was not enough data)
        """
        self.ml_trained = False
        pooled = self.pool(prepared_data)
        if pooled.empty:
            return {}
        try:
            self.ml_performance = self.predictor.train_evaluate_and_refit(pooled)
            self.ml_trained = bool(self.predictor.models)
        except ValueError as e:
            logger.warning(f"Skipping ML models: {e}")
            self.ml_performance = {}

        self.volatility_performance = {}
        if self.volatility_enabled:
            try:
                self.volatility_performance = self.volatility.fit(pooled)
            except ValueError as e:
                logger.warning(f"Skipping volatility model: {e}")
        return self.ml_performance

    def train_long_term(self, prepared_data: Dict[str, pd.DataFrame]) -> bool:
        """
        Train the long-term model (same inputs, about a month ahead). It is
        retrained at every analysis, even with a pinned short-term model: it
        is cheap, and it is shown only with its own evidence.
        """
        self.long_predictor, self.long_performance = None, {}
        if not self.long_horizon:
            return False
        pooled = self.pool(prepared_data)
        if pooled.empty:
            return False
        predictor = make_long_predictor(self.config.get('ml_config', {}), self.long_horizon)
        try:
            self.long_performance = predictor.train_evaluate_and_refit(pooled)
        except ValueError as e:
            logger.warning(f"Skipping the long-term model: {e}")
            return False
        self.long_predictor = predictor if predictor.models else None
        return self.long_predictor is not None

    def long_term_summary(self) -> Optional[Dict[str, Any]]:
        """The long-term model's horizon, out-of-sample evidence and learned weights, for the analysis summary."""
        if self.long_predictor is None:
            return None
        ensemble = self.long_performance.get('ensemble', {})
        return {
            'horizon_days': self.long_horizon,
            'model_quality': {k: v for k, v in ensemble.items() if k != 'reliability'},
            'weights': [{'feature': f, 'label': any_feature_label(f), 'weight': float(w)}
                        for f, w in sorted(self.long_predictor.coefficients().items(), key=lambda kv: -abs(kv[1]))],
        }

    def save_models(self, path: Optional[str] = None) -> str:
        """Persist this pipeline's trained return models (one file per universe)."""
        path = path or self.model_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.predictor.save_models(path)
        return path

    def export_models(self, directory: str) -> str:
        """
        Write everything needed to predict without retraining (return models,
        calibrator, volatility models and their test scores) to ``directory``.
        """
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, 'models.joblib')
        joblib.dump({
            'format': 1,
            'universe': self.universe,
            'horizon': self.horizon,
            'predictor': {
                'kind': getattr(self.predictor, 'kind', 'legacy'),
                'models': {k: v for k, v in self.predictor.models.items() if k != 'lstm'},
                'scalers': getattr(self.predictor, 'scalers', {}),
                'calibrator': self.predictor.calibrator,
                'feature_columns': self.predictor.feature_columns,
                'feature_importance': self.predictor.feature_importance,
                'model_performance': self.predictor.model_performance,
                'config': self.predictor.config,
            },
            'volatility': self.volatility if self.volatility.classifier is not None else None,
            'ml_performance': self.ml_performance,
            'volatility_performance': self.volatility_performance,
        }, path)
        with open(os.path.join(directory, 'features.txt'), 'w') as f:
            f.write('\n'.join(self.predictor.feature_columns) + '\n')
        return path

    def import_models(self, directory: str) -> None:
        """Load models written by ``export_models`` and rank with them from now on."""
        data = joblib.load(os.path.join(directory, 'models.joblib'))
        if data.get('universe') not in (None, self.universe):
            raise ValueError(f"These models belong to '{data['universe']}', not '{self.universe}'")
        state = data['predictor']
        self.predictor = make_predictor(state['config'], kind=state.get('kind', 'legacy'))
        self.predictor.models = state['models']
        self.predictor.scalers = state.get('scalers', {})
        self.predictor.calibrator = state['calibrator']
        self.predictor.feature_columns = state['feature_columns']
        self.predictor.feature_importance = state['feature_importance']
        self.predictor.model_performance = state['model_performance']
        self.predictor.config = state['config']
        if data.get('volatility') is not None:
            self.volatility = data['volatility']
        # Exports made before the overlap fix overstate their evidence; older ones also lack 'horizon'
        horizon = data.get('horizon') or self.horizon
        self.ml_performance = {k: correct_overlap(v, horizon) if isinstance(v, dict) else v
                               for k, v in data.get('ml_performance', {}).items()}
        self.volatility_performance = data.get('volatility_performance', {})
        self.ml_trained = bool(self.predictor.models)
        self.reuse_models = True

    def check_model_features(self, prepared_data: Dict[str, pd.DataFrame]) -> None:
        """Fail clearly if loaded models expect features the current data does not have."""
        columns = set().union(*(d.columns for d in prepared_data.values())) if prepared_data else set()
        missing = [c for c in self.predictor.feature_columns if c not in columns]
        if self.volatility.classifier is not None:
            missing += [c for c in self.volatility.features if c not in columns and c not in missing]
        if missing:
            raise ValueError(
                f"The loaded models need features the data no longer has ({', '.join(missing[:5])}"
                f"{'…' if len(missing) > 5 else ''}). The settings changed since they were trained: "
                f"retrain (unpin the model) instead.")
