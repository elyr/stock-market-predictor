"""
Machine learning models for stock return prediction.

The models are trained on a *pooled* dataset: rows from every stock in the
universe stacked together, each row describing one stock on one day. Only
scale-free features (returns, ratios, oscillators, percentages) are used, so a
$30 stock and a $3,000 stock are comparable and one model can learn from all of
them.

Evaluation is chronological with a purge gap: the test set starts ``horizon``
trading days after the last training date, so no training label overlaps the
test period. Probabilities are calibrated on the hold-out set, and the main
quality metric is the information coefficient (rank correlation between the
predicted probability and the realised return across stocks on each date).
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
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)

# Columns that are targets, identifiers or corporate-action noise, never features
NON_FEATURE_COLUMNS = {
    'Target_Up', 'Target_Up_Rel', 'Target_XS', 'Target_Direction', 'Target_Return', 'Target_Vol_Up',
    'Future_Close', 'Future_Return', 'Future_Excess', 'Future_Vol', 'Universe_Future_Return',
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

FEATURE_LABELS = {
    'Daily_Return': "Today's return", 'Log_Return': "Today's log return",
    'ROC_1d': '1-day return', 'ROC_5d': '5-day return', 'ROC_10d': '10-day return', 'ROC_20d': '20-day return',
    'RSI': 'RSI', 'Stoch_K': 'Stochastic %K', 'Stoch_D': 'Stochastic %D', 'MFI': 'Money flow index',
    'CCI': 'CCI', 'ADX': 'Trend strength (ADX)', 'BB_Position': 'Position in Bollinger band',
    'Volume_Ratio': 'Volume vs 20-day average', 'Volatility_5d': '5-day volatility',
    'Volatility_20d': '20-day volatility', 'Volatility_60d': '60-day volatility',
    'Vol_Ratio_5_20': 'Short vs long volatility', 'ATR_Pct': 'Average true range (% of price)',
    'MACD_Pct': 'MACD (% of price)', 'MACD_Hist_Pct': 'MACD histogram (% of price)',
    'Price_Distance_SMA_20': 'Distance from 20-day average', 'Price_Distance_SMA_50': 'Distance from 50-day average',
    'Price_Distance_SMA_200': 'Distance from 200-day average', 'Range_Position': 'Position in 20-day range',
    'Distance_to_Resistance': 'Distance to resistance', 'Distance_to_Support': 'Distance to support',
    'Abs_Return': 'Size of today\'s move', 'Range_Pct': 'Daily range (% of price)',
    'Gap_Size_Pct': 'Overnight gap', 'Williams_R_14': 'Williams %R', 'Williams_R_20': 'Williams %R (20)',
    'DI_Plus': 'Upward directional movement', 'DI_Minus': 'Downward directional movement',
    'Price_Change_Pct': 'Open-to-close move', 'Body_Size_Pct': 'Candle body size',
    'ROC_5d_vs_Universe': '5-day return vs. other stocks', 'ROC_20d_vs_Universe': '20-day return vs. other stocks',
    'ROC_20d_Rank': '20-day return rank', 'ROC_5d_vs_BTC': '5-day return vs. Bitcoin',
    'ROC_20d_vs_BTC': '20-day return vs. Bitcoin', 'Beta_BTC_30d': 'Beta to Bitcoin (30d)',
    'Corr_BTC_30d': 'Correlation with Bitcoin (30d)', 'BTC_ROC_5d': "Bitcoin's 5-day return",
    'Market_Vol_5d': 'Market volatility (5d)', 'Market_Vol_20d': 'Market volatility (20d)',
    'Market_Return_5d': "Market's 5-day return", 'BB_Width_Pct': 'Bollinger band width',
    'CCI_14': 'CCI (14)', 'CCI_20': 'CCI (20)', 'Consecutive_Up': 'Up day',
}


def feature_label(name: str) -> str:
    """Human-readable name for a feature column."""
    return FEATURE_LABELS.get(name, name.replace('_', ' '))


def select_feature_columns(data: pd.DataFrame) -> List[str]:
    """
    Pick the columns usable as model features.

    Keeps numeric and boolean columns that are scale-free. Chart-pattern columns
    (``Pattern_*``) are excluded because they only describe the latest window, and
    the cross-sectional model's ranked ``XS_*`` features belong to that model.

    Args:
        data: Prepared DataFrame with indicators

    Returns:
        Sorted list of feature column names
    """
    columns = []
    for col in data.columns:
        if col in NON_FEATURE_COLUMNS or col.startswith(('Pattern_', 'XS_')):
            continue
        if SCALE_DEPENDENT_PATTERN.match(col):
            continue
        if pd.api.types.is_bool_dtype(data[col]) or pd.api.types.is_numeric_dtype(data[col]):
            columns.append(col)
    return sorted(columns)


def to_matrix(data: pd.DataFrame, feature_columns: List[str]) -> pd.DataFrame:
    """Align a frame to the given feature columns, with NaN/inf replaced by 0."""
    X = data.reindex(columns=feature_columns).astype(float)
    return X.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def chronological_split(index: pd.Index, test_size: float, purge_days: int = 0) -> Tuple[np.ndarray, np.ndarray]:
    """
    Boolean train/test masks splitting by date, with a purge gap in between.

    The last ``test_size`` fraction of dates is the test set. The ``purge_days``
    dates immediately before it are dropped from training, because their labels
    (which look ``purge_days`` ahead) overlap the test period.
    """
    dates = pd.Index(index.unique()).sort_values()
    if test_size <= 0 or len(dates) < 3:
        return np.ones(len(index), dtype=bool), np.zeros(len(index), dtype=bool)
    split = int(len(dates) * (1 - test_size))
    test_start = dates[split]
    train_end = dates[max(0, split - purge_days)]
    return np.asarray(index < train_end), np.asarray(index >= test_start)


def information_coefficient(scores: pd.Series, returns: pd.Series, dates: pd.Index) -> Dict[str, float]:
    """
    Daily rank IC: Spearman correlation between scores and realised returns
    across stocks on each date, summarised over dates.

    Returns mean IC, its standard deviation, a t-statistic, the share of dates
    with positive IC and the number of dates.
    """
    frame = pd.DataFrame({'score': np.asarray(scores), 'ret': np.asarray(returns)}, index=dates).dropna()
    daily = []
    for _, group in frame.groupby(level=0):
        if len(group) >= 5 and group['score'].nunique() > 1 and group['ret'].nunique() > 1:
            daily.append(spearmanr(group['score'], group['ret'])[0])
    daily = pd.Series(daily, dtype=float).dropna()
    if daily.empty:
        return {'ic_mean': float('nan'), 'ic_std': float('nan'), 'ic_t_stat': float('nan'),
                'ic_positive_share': float('nan'), 'ic_days': 0}
    std = daily.std()
    return {
        'ic_mean': float(daily.mean()),
        'ic_std': float(std) if len(daily) > 1 else float('nan'),
        'ic_t_stat': float(daily.mean() / std * np.sqrt(len(daily))) if len(daily) > 1 and std > 0 else float('nan'),
        'ic_positive_share': float((daily > 0).mean()),
        'ic_days': int(len(daily)),
    }


def reliability_table(probabilities: np.ndarray, outcomes: np.ndarray, bins: int = 5) -> List[Dict[str, float]]:
    """Mean predicted probability vs observed frequency, in quantile buckets."""
    frame = pd.DataFrame({'p': probabilities, 'y': outcomes}).dropna()
    if frame['p'].nunique() < bins:
        return []
    frame['bucket'] = pd.qcut(frame['p'], bins, labels=False, duplicates='drop')
    table = frame.groupby('bucket').agg(predicted=('p', 'mean'), observed=('y', 'mean'), count=('y', 'size'))
    return [{k: float(v) for k, v in row.items()} for _, row in table.iterrows()]


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p)).reshape(-1, 1)


def _tensorflow_available() -> bool:
    try:
        import tensorflow  # noqa: F401
        return True
    except ImportError:
        return False


class StockPredictor:
    """
    Machine learning system that predicts whether a stock outperforms over the
    configured horizon (or rises in absolute terms, if configured).
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
        self.calibrator: Optional[LogisticRegression] = None
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
                'target': 'relative',  # 'relative' (beat the universe) or 'absolute' (go up)
                'horizon': 5,
                'test_size': 0.2,
                'cross_validate': True,
                'cv_splits': 3,
                'min_samples': 200,
                'calibrate': True,
            },
        }

    def _merge_config(self, config: Dict) -> Dict:
        merged = copy.deepcopy(self._default_config())
        user = dict(config.get('models', {}))
        if 'training' in config:
            user['training'] = config['training']
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

    @property
    def target_column(self) -> str:
        return 'Target_Up_Rel' if self.config['training'].get('target') == 'relative' else 'Target_Up'

    @property
    def return_column(self) -> str:
        return 'Future_Excess' if self.config['training'].get('target') == 'relative' else 'Future_Return'

    @property
    def horizon(self) -> int:
        return int(self.config['training'].get('horizon', 1))

    def _model_params(self, name: str, exclude: Tuple[str, ...] = ()) -> Dict[str, Any]:
        skip = {'enabled'} | set(exclude)
        return {k: v for k, v in self.config[name].items() if k not in skip}

    # ------------------------------------------------------------------ data

    def _training_frame(self, data: pd.DataFrame, target_column: str = None) -> pd.DataFrame:
        target_column = target_column or self.target_column
        if target_column not in data.columns:
            raise ValueError(f"Target column {target_column} missing; prepare data with the matching target")
        return data.dropna(subset=[target_column]).sort_index(kind='stable')

    def prepare_data(self, data: pd.DataFrame, target_column: str = None,
                     test_size: float = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, List[str]]:
        """
        Prepare data with a chronological, purged split.

        Args:
            data: DataFrame with features and targets (one or many stocks)
            target_column: Defaults to the configured target
            test_size: Proportion of dates for testing (0 trains on everything)

        Returns:
            Tuple of (X_train, X_test, y_train, y_test, feature_names)
        """
        target_column = target_column or self.target_column
        if test_size is None:
            test_size = self.config['training']['test_size']

        df = self._training_frame(data, target_column)
        min_samples = self.config['training']['min_samples']
        if len(df) < min_samples:
            raise ValueError(
                f"Insufficient data for training ({len(df)} rows, minimum {min_samples} required)"
            )

        feature_columns = select_feature_columns(df)
        X = to_matrix(df, feature_columns)
        y = df[target_column].astype(int).values
        train_mask, test_mask = chronological_split(df.index, test_size, purge_days=self.horizon)

        scaler = StandardScaler()
        X_train = scaler.fit_transform(X[train_mask])
        X_test = scaler.transform(X[test_mask]) if test_mask.any() else np.empty((0, X.shape[1]))

        self.scalers['main'] = scaler
        self.feature_columns = feature_columns

        logger.info(f"Data prepared: {X_train.shape[0]} training, {X_test.shape[0]} test samples, "
                    f"{len(feature_columns)} features, target {target_column}, horizon {self.horizon}d")

        return X_train, X_test, y[train_mask], y[test_mask], feature_columns

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
            cv = TimeSeriesSplit(n_splits=training.get('cv_splits', 3), gap=self.horizon)
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
                          target_column: str = None,
                          sequence_length: int = 20) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Build (samples, sequence_length, features) arrays for the LSTM.

        Sequences never cross from one stock into another. The last 20% of
        sequences by date are used for testing.
        """
        target_column = target_column or self.target_column
        groups = data.groupby('Symbol') if 'Symbol' in data.columns else [(None, data)]
        sequences, targets, dates = [], [], []
        scaler = self.scalers.get('main')

        for _, frame in groups:
            frame = frame.sort_index()
            X = to_matrix(frame, feature_columns)
            X = scaler.transform(X) if scaler is not None else X.values
            y = frame[target_column].values
            for i in range(sequence_length, len(frame)):
                if np.isnan(y[i]):
                    continue
                sequences.append(X[i - sequence_length + 1:i + 1])
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
            data: DataFrame with features and the target (one or many stocks)
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
        Measure quality on a purged chronological hold-out, calibrate, then refit.

        1. Train on the older dates and score the hold-out dates.
        2. Record per-model accuracy/AUC plus the ensemble's information
           coefficient, Brier score and reliability table under ``'ensemble'``.
        3. Fit a calibrator mapping the ensemble's raw probability to the
           frequency actually observed on the hold-out.
        4. Refit every model on all rows so predictions use the latest history.
        """
        self.calibrator = None
        performance = self.train_all_models(data)
        tabular = [k for k in performance if k != 'lstm' and 'probabilities' in performance[k]]
        if not tabular:
            return performance

        frame = self._training_frame(data)
        _, test_mask = chronological_split(frame.index, self.config['training']['test_size'], self.horizon)
        test = frame[test_mask]
        raw = np.mean([performance[k]['probabilities'] for k in tabular], axis=0)
        y_test = test[self.target_column].astype(int).values

        if self.config['training'].get('calibrate', True) and len(np.unique(y_test)) > 1:
            self.calibrator = LogisticRegression(C=1.0).fit(_logit(raw), y_test)
        calibrated = self._calibrate(raw)

        performance['ensemble'] = {
            'test_accuracy': float(accuracy_score(y_test, (calibrated > 0.5).astype(int))),
            'test_auc': float(roc_auc_score(y_test, raw)) if len(np.unique(y_test)) > 1 else None,
            'test_base_rate': float(np.mean(y_test)),
            'brier_raw': float(brier_score_loss(y_test, raw)),
            'brier_calibrated': float(brier_score_loss(y_test, calibrated)),
            'reliability': reliability_table(calibrated, y_test),
            'test_rows': int(len(test)),
            'test_start': str(test.index.min().date()) if len(test) else None,
            'test_end': str(test.index.max().date()) if len(test) else None,
            **information_coefficient(raw, test[self.return_column], test.index),
        }
        calibrator = self.calibrator
        self.train_all_models(data, test_size=0, cross_validate=False)
        self.calibrator = calibrator
        self.model_performance = performance
        return performance

    # ------------------------------------------------------------ prediction

    def _calibrate(self, probabilities: np.ndarray) -> np.ndarray:
        if self.calibrator is None:
            return probabilities
        return self.calibrator.predict_proba(_logit(probabilities))[:, 1]

    def predict(self, data: pd.DataFrame, model_name: str = 'ensemble') -> Dict[str, Any]:
        """
        Predict the probability of the target for each row.

        Args:
            data: DataFrame with the same feature columns used in training
            model_name: A trained model's name, or 'ensemble' to average them

        Returns:
            Dictionary with 'predictions', 'probabilities' (calibrated for the
            ensemble when a calibrator exists), 'raw_probabilities' and, for the
            ensemble, 'individual_probabilities' keyed by model name
        """
        tabular = {k: m for k, m in self.models.items() if k != 'lstm'}
        if not tabular:
            raise ValueError("No trained models available. Train models first.")

        X = self.scalers['main'].transform(to_matrix(data, self.feature_columns))

        if model_name == 'ensemble':
            individual = {name: model.predict_proba(X)[:, 1] for name, model in tabular.items()}
            raw = np.mean(list(individual.values()), axis=0)
            probabilities = self._calibrate(raw)
            return {
                'predictions': (probabilities > 0.5).astype(int),
                'probabilities': probabilities,
                'raw_probabilities': raw,
                'individual_probabilities': individual,
                'individual_predictions': {k: (v > 0.5).astype(int) for k, v in individual.items()},
            }

        if model_name not in tabular:
            raise ValueError(f"Model {model_name} not found")
        probabilities = tabular[model_name].predict_proba(X)[:, 1]
        return {'predictions': (probabilities > 0.5).astype(int), 'probabilities': probabilities,
                'raw_probabilities': probabilities}

    def explain(self, row: pd.DataFrame, top_n: int = 6) -> List[Dict[str, Any]]:
        """
        Feature contributions to the XGBoost model's prediction for one row.

        Uses XGBoost's exact tree SHAP values (log-odds units): positive pushes
        the prediction towards outperforming, negative away from it.

        Returns:
            Up to ``top_n`` dicts with feature, label, value and contribution,
            largest absolute contribution first
        """
        model = self.models.get('xgboost')
        if model is None or row.empty:
            return []
        raw = to_matrix(row.tail(1), self.feature_columns)
        X = self.scalers['main'].transform(raw)
        contributions = model.get_booster().predict(xgb.DMatrix(X), pred_contribs=True)[0][:-1]
        order = np.argsort(-np.abs(contributions))[:top_n]
        return [{
            'feature': self.feature_columns[i],
            'label': feature_label(self.feature_columns[i]),
            'value': float(raw.iloc[0, i]),
            'contribution': float(contributions[i]),
        } for i in order if contributions[i] != 0]

    def get_feature_importance(self, model_name: str = 'random_forest', top_n: int = 20) -> List[Tuple[str, float]]:
        """Top features by importance for a tree model."""
        importance = self.feature_importance.get(model_name, {})
        return sorted(importance.items(), key=lambda x: x[1], reverse=True)[:top_n]

    def save_models(self, filepath: str) -> None:
        """Save trained models to file (LSTM excluded; it is not picklable)."""
        joblib.dump({
            'models': {k: v for k, v in self.models.items() if k != 'lstm'},
            'scalers': self.scalers,
            'calibrator': self.calibrator,
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
        self.calibrator = model_data.get('calibrator')
        self.feature_columns = model_data.get('feature_columns', [])
        self.feature_importance = model_data['feature_importance']
        self.model_performance = model_data['model_performance']
        self.config = model_data['config']
        logger.info(f"Models loaded from {filepath}")
