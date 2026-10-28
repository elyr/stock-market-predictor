"""
Machine learning models for stock price prediction.

The models are trained on a *pooled* dataset: rows from every stock in the
universe stacked together, each row describing one stock on one day. Only
scale-free features (returns, ratios, oscillators, percentages) are used, so a
$30 stock and a $3,000 stock are comparable and one model can learn from all of
them. Splits are chronological so the test set is always in the future
relative to the training set.
"""

import copy
import logging
import re
import warnings
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)

# Columns that are targets, identifiers or corporate-action noise, never features
NON_FEATURE_COLUMNS = {
    'Target_Up', 'Target_Direction', 'Target_Return', 'Future_Close', 'Future_Return',
    'Symbol', 'Date', 'Dividends', 'Stock Splits', 'Capital Gains',
}

# Price- or volume-denominated columns. Their raw level differs by stock, so
# they are excluded in favour of the normalised versions computed alongside them
# (e.g. Price_Distance_SMA_20 instead of SMA_20, ATR_Pct instead of ATR).
SCALE_DEPENDENT_PATTERN = re.compile(
    r'^(Open|High|Low|Close|Adj Close|Volume|Price_Range|Price_Change|Price_Volume|'
    r'Volume_MA_\d+|Gap_Size|True_Range|SMA_\d+|EMA_\d+|Volume_SMA_\d+|Momentum_\d+d|'
    r'Body_Size|Upper_Shadow|Lower_Shadow|Resistance|Support|MACD|MACD_Signal|'
    r'MACD_Histogram|BB_Upper|BB_Middle|BB_Lower|BB_Width|ATR|OBV)$'
)


def select_feature_columns(data: pd.DataFrame) -> List[str]:
    """
    Pick the columns usable as model features.

    Keeps numeric and boolean columns that are scale-free. Chart-pattern columns
    (``Pattern_*``) are excluded because they only describe the latest window.

    Args:
        data: Prepared DataFrame with indicators

    Returns:
        Sorted list of feature column names
    """
    columns = []
    for col in data.columns:
        if col in NON_FEATURE_COLUMNS or col.startswith('Pattern_'):
            continue
        if SCALE_DEPENDENT_PATTERN.match(col):
            continue
        if pd.api.types.is_bool_dtype(data[col]) or pd.api.types.is_numeric_dtype(data[col]):
            columns.append(col)
    return sorted(columns)


def _to_matrix(data: pd.DataFrame, feature_columns: List[str]) -> pd.DataFrame:
    """Align a frame to the given feature columns, with NaN/inf replaced by 0."""
    X = data.reindex(columns=feature_columns).astype(float)
    return X.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _tensorflow_available() -> bool:
    try:
        import tensorflow  # noqa: F401
        return True
    except ImportError:
        return False


class StockPredictor:
    """
    Machine learning system that predicts whether a stock closes higher tomorrow.
    """

    def __init__(self, config: Dict = None):
        """
        Initialize with configuration.

        Accepts either the flat form (``{'random_forest': {...}, ...}``) or the
        ``ml_config`` section of config.yaml (``{'models': {...}, 'training': {...}}``).
        """
        self.config = self._merge_config(config or {})
        self.models: Dict[str, Any] = {}
        self.scalers: Dict[str, StandardScaler] = {}
        self.feature_columns: List[str] = []
        self.feature_importance: Dict[str, Dict[str, float]] = {}
        self.model_performance: Dict[str, Dict[str, Any]] = {}
        self._cv_override: Optional[bool] = None

    def _default_config(self) -> Dict:
        """Default configuration for ML models."""
        return {
            'random_forest': {
                'enabled': True,
                'n_estimators': 200,
                'max_depth': 6,
                'min_samples_leaf': 20,
                'random_state': 42,
                'n_jobs': -1,
            },
            'xgboost': {
                'enabled': True,
                'n_estimators': 200,
                'max_depth': 3,
                'learning_rate': 0.05,
                'subsample': 0.8,
                'colsample_bytree': 0.8,
                'random_state': 42,
                'n_jobs': -1,
            },
            'neural_network': {
                'enabled': True,
                'hidden_layers': [64, 32],
                'alpha': 0.001,
                'max_iter': 200,
                'random_state': 42,
            },
            'lstm': {
                'enabled': False,  # needs TensorFlow; slow and rarely better here
                'units': [32],
                'dropout_rate': 0.2,
                'epochs': 20,
                'batch_size': 64,
                'sequence_length': 20,
            },
            'training': {
                'test_size': 0.2,
                'cross_validate': True,
                'cv_splits': 3,
                'min_samples': 200,
            },
        }

    def _merge_config(self, config: Dict) -> Dict:
        merged = copy.deepcopy(self._default_config())
        user = dict(config.get('models', {}))
        for key in ('training',):
            if key in config:
                user[key] = config[key]
        # Also accept the flat form
        for key in merged:
            if key in config and isinstance(config[key], dict):
                user.setdefault(key, config[key])
        for key, value in user.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
        return merged

    def _model_params(self, name: str, exclude: Tuple[str, ...] = ()) -> Dict[str, Any]:
        skip = {'enabled'} | set(exclude)
        return {k: v for k, v in self.config[name].items() if k not in skip}

    # ------------------------------------------------------------------ data

    def prepare_data(self, data: pd.DataFrame, target_column: str = 'Target_Up',
                     test_size: float = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, List[str]]:
        """
        Prepare data for machine learning with a chronological split.

        Rows are ordered by date and the last ``test_size`` fraction of dates is
        held out, so the model is always evaluated on data after what it saw.

        Args:
            data: DataFrame with features and targets (one or many stocks)
            target_column: Name of target column
            test_size: Proportion of dates for testing (0 trains on everything)

        Returns:
            Tuple of (X_train, X_test, y_train, y_test, feature_names)
        """
        if test_size is None:
            test_size = self.config['training']['test_size']

        df = data.dropna(subset=[target_column]).sort_index(kind='stable')
        min_samples = self.config['training']['min_samples']
        if len(df) < min_samples:
            raise ValueError(
                f"Insufficient data for training ({len(df)} rows, minimum {min_samples} required)"
            )

        feature_columns = select_feature_columns(df)
        X = _to_matrix(df, feature_columns)
        y = df[target_column].astype(int).values

        if test_size > 0:
            dates = df.index.unique().sort_values()
            split_date = dates[int(len(dates) * (1 - test_size))]
            train_mask = df.index < split_date
        else:
            train_mask = np.ones(len(df), dtype=bool)

        scaler = StandardScaler()
        X_train = scaler.fit_transform(X[train_mask])
        X_test = scaler.transform(X[~train_mask]) if (~train_mask).any() else np.empty((0, X.shape[1]))

        self.scalers['main'] = scaler
        self.feature_columns = feature_columns

        logger.info(f"Data prepared: {X_train.shape[0]} training, {X_test.shape[0]} test samples, "
                    f"{len(feature_columns)} features")

        return X_train, X_test, y[train_mask], y[~train_mask], feature_columns

    def _evaluate(self, name: str, model, X_train, y_train, X_test, y_test) -> Dict[str, Any]:
        """Shared metrics for the scikit-learn style classifiers."""
        performance: Dict[str, Any] = {
            'train_accuracy': accuracy_score(y_train, model.predict(X_train)),
        }
        if len(y_test):
            y_pred = model.predict(X_test)
            y_proba = model.predict_proba(X_test)[:, 1]
            performance.update({
                'test_accuracy': accuracy_score(y_test, y_pred),
                'test_auc': roc_auc_score(y_test, y_proba) if len(np.unique(y_test)) > 1 else None,
                'test_base_rate': float(np.mean(y_test)),
                'predictions': y_pred,
                'probabilities': y_proba,
            })

        training = self.config['training']
        cross_validate = training.get('cross_validate') if self._cv_override is None else self._cv_override
        if cross_validate and len(y_train) >= 100:
            cv = TimeSeriesSplit(n_splits=training.get('cv_splits', 3))
            scores = cross_val_score(model, X_train, y_train, cv=cv, scoring='accuracy')
            performance['cv_mean'] = scores.mean()
            performance['cv_std'] = scores.std()

        self.model_performance[name] = performance
        msg = f"{name} - train acc {performance['train_accuracy']:.3f}"
        if 'test_accuracy' in performance:
            msg += f", test acc {performance['test_accuracy']:.3f} (base rate {performance['test_base_rate']:.3f})"
        logger.info(msg)
        return performance

    # ---------------------------------------------------------------- models

    def train_random_forest(self, X_train: np.ndarray, y_train: np.ndarray,
                            X_test: np.ndarray, y_test: np.ndarray,
                            feature_names: List[str]) -> Dict[str, Any]:
        """Train a Random Forest classifier."""
        logger.info("Training Random Forest model...")
        model = RandomForestClassifier(**self._model_params('random_forest'))
        model.fit(X_train, y_train)
        self.models['random_forest'] = model
        self.feature_importance['random_forest'] = dict(zip(feature_names, model.feature_importances_))
        return self._evaluate('random_forest', model, X_train, y_train, X_test, y_test)

    def train_xgboost(self, X_train: np.ndarray, y_train: np.ndarray,
                      X_test: np.ndarray, y_test: np.ndarray,
                      feature_names: List[str]) -> Dict[str, Any]:
        """Train an XGBoost classifier."""
        logger.info("Training XGBoost model...")
        model = xgb.XGBClassifier(**self._model_params('xgboost'), eval_metric='logloss')
        model.fit(X_train, y_train, verbose=False)
        self.models['xgboost'] = model
        self.feature_importance['xgboost'] = dict(zip(feature_names, model.feature_importances_))
        return self._evaluate('xgboost', model, X_train, y_train, X_test, y_test)

    def train_neural_network(self, X_train: np.ndarray, y_train: np.ndarray,
                             X_test: np.ndarray, y_test: np.ndarray) -> Dict[str, Any]:
        """Train a feed-forward neural network (scikit-learn MLP, early stopping on)."""
        logger.info("Training Neural Network model...")
        params = self._model_params('neural_network', exclude=('hidden_layers',))
        model = MLPClassifier(
            hidden_layer_sizes=tuple(self.config['neural_network']['hidden_layers']),
            early_stopping=True,
            **params,
        )
        model.fit(X_train, y_train)
        self.models['neural_network'] = model
        return self._evaluate('neural_network', model, X_train, y_train, X_test, y_test)

    def prepare_lstm_data(self, data: pd.DataFrame, feature_columns: List[str],
                          target_column: str = 'Target_Up',
                          sequence_length: int = 20) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Build (samples, sequence_length, features) arrays for the LSTM.

        Sequences never cross from one stock into another. The last 20% of
        sequences by date are used for testing.
        """
        groups = data.groupby('Symbol') if 'Symbol' in data.columns else [(None, data)]
        sequences, targets, dates = [], [], []
        scaler = self.scalers.get('main')

        for _, frame in groups:
            frame = frame.sort_index()
            X = _to_matrix(frame, feature_columns)
            X = scaler.transform(X) if scaler is not None else X.values
            y = frame[target_column].values
            for i in range(sequence_length, len(frame)):
                if np.isnan(y[i]):
                    continue
                sequences.append(X[i - sequence_length:i + 1][-sequence_length:])
                targets.append(int(y[i]))
                dates.append(frame.index[i])

        if not sequences:
            empty = np.empty((0, sequence_length, len(feature_columns)))
            return empty, empty, np.array([]), np.array([])

        order = np.argsort(np.array(dates, dtype='datetime64[ns]'), kind='stable')
        X_all, y_all = np.array(sequences)[order], np.array(targets)[order]
        split = int(len(X_all) * 0.8)
        return X_all[:split], X_all[split:], y_all[:split], y_all[split:]

    def train_lstm(self, data: pd.DataFrame, feature_columns: List[str]) -> Dict[str, Any]:
        """Train an LSTM (requires TensorFlow; disabled by default)."""
        if not _tensorflow_available():
            logger.warning("LSTM enabled in config but TensorFlow is not installed; skipping")
            return {}

        from tensorflow.keras.callbacks import EarlyStopping
        from tensorflow.keras.layers import LSTM, Dense, Dropout, Input
        from tensorflow.keras.models import Sequential

        logger.info("Training LSTM model...")
        cfg = self.config['lstm']
        X_train, X_test, y_train, y_test = self.prepare_lstm_data(
            data, feature_columns, sequence_length=cfg['sequence_length']
        )
        if len(X_train) < 50:
            logger.warning("Insufficient data for LSTM training")
            return {}

        model = Sequential([Input(shape=(X_train.shape[1], X_train.shape[2]))])
        units = cfg['units']
        for i, n in enumerate(units):
            model.add(LSTM(n, return_sequences=i < len(units) - 1))
            model.add(Dropout(cfg['dropout_rate']))
        model.add(Dense(1, activation='sigmoid'))
        model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
        model.fit(X_train, y_train, epochs=cfg['epochs'], batch_size=cfg['batch_size'],
                  validation_split=0.1, verbose=0,
                  callbacks=[EarlyStopping(monitor='val_loss', patience=3, restore_best_weights=True)])

        proba = model.predict(X_test, verbose=0).flatten()
        performance = {
            'test_accuracy': accuracy_score(y_test, (proba > 0.5).astype(int)),
            'test_base_rate': float(np.mean(y_test)),
            'probabilities': proba,
        }
        self.models['lstm'] = model
        self.model_performance['lstm'] = performance
        logger.info(f"LSTM - test acc {performance['test_accuracy']:.3f}")
        return performance

    def train_all_models(self, data: pd.DataFrame, test_size: float = None,
                         cross_validate: Optional[bool] = None) -> Dict[str, Dict[str, Any]]:
        """
        Train every enabled model.

        Args:
            data: DataFrame with features and ``Target_Up`` (one or many stocks)
            test_size: Override the configured hold-out fraction (0 = use all rows)
            cross_validate: Override the configured cross-validation setting

        Returns:
            Dictionary with each model's performance
        """
        logger.info("Training all models...")
        self.models = {}
        self.model_performance = {}
        self.feature_importance = {}
        self._cv_override = cross_validate

        X_train, X_test, y_train, y_test, feature_names = self.prepare_data(data, test_size=test_size)
        if len(np.unique(y_train)) < 2:
            raise ValueError("Training data contains only one class; cannot train classifiers")

        performances = {}
        trainers = {
            'random_forest': lambda: self.train_random_forest(X_train, y_train, X_test, y_test, feature_names),
            'xgboost': lambda: self.train_xgboost(X_train, y_train, X_test, y_test, feature_names),
            'neural_network': lambda: self.train_neural_network(X_train, y_train, X_test, y_test),
            'lstm': lambda: self.train_lstm(data, feature_names),
        }
        for name, train in trainers.items():
            if not self.config[name].get('enabled', True):
                continue
            try:
                result = train()
                if result:
                    performances[name] = result
            except Exception as e:
                logger.error(f"Error training {name}: {str(e)}")

        self._cv_override = None
        return performances

    def train_evaluate_and_refit(self, data: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """
        Measure accuracy on a chronological hold-out, then refit on all data.

        The returned (and stored) performance describes the hold-out run; the
        models kept for prediction are the ones refit on every row, so they
        include the most recent history.
        """
        performance = self.train_all_models(data)
        if performance:
            self.train_all_models(data, test_size=0, cross_validate=False)
            self.model_performance = performance
        return performance

    # ------------------------------------------------------------ prediction

    def predict(self, data: pd.DataFrame, model_name: str = 'ensemble') -> Dict[str, Any]:
        """
        Predict the probability that each row's stock closes higher next day.

        Args:
            data: DataFrame with the same feature columns used in training
            model_name: A trained model's name, or 'ensemble' to average them

        Returns:
            Dictionary with 'predictions', 'probabilities' and, for the ensemble,
            'individual_probabilities' keyed by model name
        """
        tabular = {k: m for k, m in self.models.items() if k != 'lstm'}
        if not tabular:
            raise ValueError("No trained models available. Train models first.")

        X = self.scalers['main'].transform(_to_matrix(data, self.feature_columns))

        if model_name == 'ensemble':
            individual = {name: model.predict_proba(X)[:, 1] for name, model in tabular.items()}
            probabilities = np.mean(list(individual.values()), axis=0)
            return {
                'predictions': (probabilities > 0.5).astype(int),
                'probabilities': probabilities,
                'individual_probabilities': individual,
                'individual_predictions': {k: (v > 0.5).astype(int) for k, v in individual.items()},
            }

        if model_name not in tabular:
            raise ValueError(f"Model {model_name} not found")
        probabilities = tabular[model_name].predict_proba(X)[:, 1]
        return {'predictions': (probabilities > 0.5).astype(int), 'probabilities': probabilities}

    def get_feature_importance(self, model_name: str = 'random_forest', top_n: int = 20) -> List[Tuple[str, float]]:
        """Top features by importance for a tree model."""
        importance = self.feature_importance.get(model_name, {})
        return sorted(importance.items(), key=lambda x: x[1], reverse=True)[:top_n]

    def save_models(self, filepath: str) -> None:
        """Save trained models to file (LSTM excluded; it is not picklable)."""
        joblib.dump({
            'models': {k: v for k, v in self.models.items() if k != 'lstm'},
            'scalers': self.scalers,
            'feature_columns': self.feature_columns,
            'feature_importance': self.feature_importance,
            'model_performance': self.model_performance,
            'config': self.config,
        }, filepath)
        logger.info(f"Models saved to {filepath}")

    def load_models(self, filepath: str) -> None:
        """Load trained models from file."""
        model_data = joblib.load(filepath)
        self.models = model_data['models']
        self.scalers = model_data['scalers']
        self.feature_columns = model_data.get('feature_columns', [])
        self.feature_importance = model_data['feature_importance']
        self.model_performance = model_data['model_performance']
        self.config = model_data['config']
        logger.info(f"Models loaded from {filepath}")
