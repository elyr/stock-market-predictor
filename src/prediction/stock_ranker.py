"""
Ranking pipeline: data -> features -> models -> scores -> picks.

``StockRanker`` holds everything shared by all asset classes. The concrete
pipelines in :mod:`src.prediction.pipelines` (``StockPipeline`` and
``CryptoPipeline``) subclass it to add asset-class-specific features, filters
and metadata. Each pipeline instance owns its own models, so stocks and crypto
are trained and evaluated completely separately.
"""

import logging
import os
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.analysis.sentiment_analysis import SentimentAnalyzer
from src.analysis.technical_indicators import TechnicalAnalyzer
from src.data.collector import PROJECT_ROOT, DataCollector, load_config, resolve_config_path
from src.data.preprocessor import DataPreprocessor, add_relative_targets
from src.models.evaluation import ModelEvaluator
from src.models.ml_models import StockPredictor
from src.models.volatility import VolatilityForecaster, add_market_volatility
from src.prediction.portfolio import select_portfolio
from src.utils.helpers import recommendation_label

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {
    'technical_score': 0.25,
    'ml_prediction': 0.35,
    'momentum_score': 0.20,
    'volume_score': 0.10,
    'sentiment_score': 0.10,
}

# Scores that are computed from price/volume history alone (usable in backtests)
PRICE_BASED_COMPONENTS = ('technical_score', 'momentum_score', 'volume_score')

DEFAULT_UNIVERSES = {
    'stocks': {
        'label': 'US Stocks', 'symbols': [], 'timeframe': '2y', 'periods_per_year': 252,
        'use_sentiment': True,
        'filters': {'min_price': 5.0, 'max_price': 0, 'min_volume': 1_000_000,
                    'min_market_cap': 1e9, 'exclude_penny_stocks': True},
        'portfolio': {'max_per_sector': 3, 'weighting': 'inverse_volatility'},
    },
    'crypto': {
        'label': 'Crypto', 'symbols': [], 'timeframe': '2y', 'periods_per_year': 365,
        'use_sentiment': False,
        'filters': {'min_price': 0, 'max_price': 0, 'min_volume': 10_000_000,
                    'min_market_cap': 1e9, 'exclude_penny_stocks': False},
        'portfolio': {'max_per_sector': 0, 'weighting': 'inverse_volatility'},
    },
}


def apply_overrides(config: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``config`` with dotted-path keys (``'a.b.c': value``) set."""
    import copy
    result = copy.deepcopy(config)
    for path, value in overrides.items():
        node = result
        keys = path.split('.')
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
    return result


def composite_score(scores: Dict[str, float], weights: Dict[str, float]) -> float:
    """
    Weighted average of the available component scores.

    Weights are renormalised over the components present, so leaving one out
    (e.g. sentiment in a backtest) does not drag the composite towards zero.
    """
    used = {k: w for k, w in weights.items() if k in scores and scores[k] is not None and w > 0}
    total = sum(used.values())
    if total == 0:
        return 50.0
    return sum(scores[k] * w for k, w in used.items()) / total


def percentile_scores(values: pd.Series) -> pd.Series:
    """Map values to 0-100 by cross-sectional rank (best = 100)."""
    if len(values) < 2:
        return pd.Series(50.0, index=values.index)
    return (values.rank(method='average') - 1) / (len(values) - 1) * 100


class StockRanker:
    """
    Shared ranking pipeline. Use :func:`src.prediction.pipelines.create_pipeline`
    to get the stock or crypto version.
    """

    asset_class = 'stocks'

    def __init__(self, config_path: str = "config/config.yaml",
                 data_collector: Optional[DataCollector] = None,
                 universe: Optional[str] = None,
                 config_overrides: Optional[Dict[str, Any]] = None):
        """
        Args:
            config_path: Path to config.yaml (relative paths also resolve from the project root)
            data_collector: Optional data source instead of live Yahoo Finance
                (tests, demo mode, other providers)
            universe: Universe key in config ``universes`` (defaults to the class's asset class)
            config_overrides: dotted-path settings applied on top of the file, e.g.
                ``{'ml_config.training.horizon': 3}`` (used by experiments)
        """
        self.config_path = resolve_config_path(config_path)
        self.config = apply_overrides(load_config(config_path), config_overrides or {})
        self.universe = universe or self.asset_class
        self.universe_config = self._universe_config()

        # Initialize components
        self.data_collector = data_collector or DataCollector(config_path)
        self.preprocessor = DataPreprocessor()
        self.technical_analyzer = TechnicalAnalyzer(self.config.get('technical_analysis', {}))
        self.sentiment_analyzer = SentimentAnalyzer()
        self.predictor = StockPredictor(self.config.get('ml_config', {}))
        self.evaluator = ModelEvaluator()

        vol_cfg = self.config.get('volatility', {})
        self.volatility_enabled = vol_cfg.get('enabled', True)
        self.volatility = VolatilityForecaster(horizon=vol_cfg.get('horizon', 5),
                                               periods_per_year=self.periods_per_year)

        # Ranking configuration
        self.ranking_config = self.config.get('ranking_config', {})
        self.weights = {**DEFAULT_WEIGHTS, **self.ranking_config.get('weights', {})}
        self.filters = self.universe_config['filters']
        self.portfolio_config = self.universe_config['portfolio']
        self.use_sentiment = self.universe_config.get('use_sentiment', True)
        self.target_threshold = self.config.get('ml_config', {}).get('training', {}).get('target_threshold', 0.0)

        self.ml_trained = False
        self.ml_performance: Dict[str, Dict[str, Any]] = {}
        self.volatility_performance: Dict[str, Any] = {}
        self.last_prepared: Dict[str, pd.DataFrame] = {}

        logger.info(f"{self.__class__.__name__} initialized for universe '{self.universe}'")

    # ----------------------------------------------------------- settings

    def _universe_config(self) -> Dict[str, Any]:
        base = DEFAULT_UNIVERSES.get(self.universe, DEFAULT_UNIVERSES['stocks'])
        user = self.config.get('universes', {}).get(self.universe, {})
        merged = {**base, **user}
        merged['filters'] = {**base['filters'], **user.get('filters', {})}
        merged['portfolio'] = {**base['portfolio'], **user.get('portfolio', {})}
        # Legacy layout (stock_config / ranking_config.filters)
        if self.universe == 'stocks' and not user:
            legacy = self.config.get('stock_config', {})
            merged['symbols'] = legacy.get('symbols', merged['symbols'])
            merged['timeframe'] = legacy.get('timeframe', merged['timeframe'])
            merged['filters'].update(self.config.get('ranking_config', {}).get('filters', {}))
        return merged

    @property
    def symbols(self) -> List[str]:
        return list(self.universe_config.get('symbols', []))

    @property
    def periods_per_year(self) -> int:
        return int(self.universe_config.get('periods_per_year', 252))

    @property
    def horizon(self) -> int:
        return self.predictor.horizon

    @property
    def label(self) -> str:
        return self.universe_config.get('label', self.universe)

    def model_path(self) -> str:
        return os.path.join(PROJECT_ROOT, 'data', 'models', f'{self.universe}.joblib')

    # ------------------------------------------------------------------ data

    def prepare_symbol_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        """
        Run the per-asset feature pipeline on raw OHLCV data.

        Every feature at date t uses only data up to t. The targets look
        ``horizon`` days ahead and are NaN where the future is unknown.
        """
        data = self.preprocessor.clean_stock_data(raw)
        data = self.preprocessor.add_basic_features(data)
        data = self.preprocessor.add_moving_averages(data)
        data = self.preprocessor.add_momentum_features(data)
        data = self.preprocessor.add_pattern_features(data)
        data = self.preprocessor.add_support_resistance(data)
        data = self.technical_analyzer.calculate_all_indicators(data)
        data = self.preprocessor.create_target_variable(data, horizon=self.horizon,
                                                        threshold=self.target_threshold)
        data = self.preprocessor.add_volatility_targets(data, horizon=self.volatility.horizon)
        return data

    def add_universe_features(self, prepared: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """Asset-class-specific cross-sectional features. Overridden by subclasses."""
        return prepared

    def prepare_universe(self, raw_data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """
        Prepare every asset, then add features and targets that need the whole universe
        (relative returns, market volatility, asset-class features).
        """
        prepared = {}
        for symbol, data in raw_data.items():
            try:
                if data is None or data.empty:
                    logger.warning(f"No data available for {symbol}")
                    continue
                prepared[symbol] = self.prepare_symbol_data(data)
            except Exception as e:
                logger.error(f"Error preparing data for {symbol}: {str(e)}")
        prepared = add_relative_targets(prepared)
        prepared = add_market_volatility(prepared)
        prepared = self.add_universe_features(prepared)
        return prepared

    def fetch_and_prepare_data(self, symbols: List[str], period: str = None) -> Dict[str, pd.DataFrame]:
        """
        Fetch and prepare data for all symbols.

        Args:
            symbols: Ticker symbols
            period: History to fetch (defaults to the universe's timeframe)
        """
        logger.info(f"Fetching data for {len(symbols)} symbols...")
        period = period or self.universe_config.get('timeframe', '2y')
        raw_data = self.data_collector.fetch_multiple_stocks(symbols, period=period)
        prepared = self.prepare_universe(raw_data)
        logger.info(f"Successfully prepared data for {len(prepared)} symbols")
        return prepared

    # ---------------------------------------------------------------- scores

    def calculate_technical_score(self, data: pd.DataFrame, patterns: Dict[str, bool] = None) -> float:
        """
        Calculate technical analysis score (0-100) from the latest row.

        Args:
            data: Prepared data
            patterns: Chart patterns for the latest window; read from the
                ``Pattern_*`` columns of the latest row when not given
        """
        if data.empty:
            return 0.0

        latest = data.iloc[-1]
        score_components = []

        try:
            rsi = latest.get('RSI', np.nan)
            if pd.notna(rsi):
                score_components.append(90 if rsi < 30 else 70 if rsi < 50 else 50 if rsi < 70 else 20)

            if pd.notna(latest.get('MACD', np.nan)) and pd.notna(latest.get('MACD_Signal', np.nan)):
                macd_score = 80 if latest['MACD'] > latest['MACD_Signal'] else 20
                if latest.get('MACD_Cross_Up', 0):
                    macd_score += 20
                score_components.append(min(macd_score, 100))

            bb_position = latest.get('BB_Position', np.nan)
            if pd.notna(bb_position):
                score_components.append(90 if bb_position < 0.2 else 70 if bb_position < 0.5
                                        else 50 if bb_position < 0.8 else 20)

            sma_scores = [80 if latest[f'Price_Above_SMA_{p}'] else 20
                          for p in (20, 50)
                          if f'Price_Above_SMA_{p}' in latest and pd.notna(latest.get(f'SMA_{p}', np.nan))]
            if sma_scores:
                score_components.append(np.mean(sma_scores))

            volume_ratio = latest.get('Volume_Ratio', np.nan)
            if pd.notna(volume_ratio):
                score_components.append(80 if volume_ratio > 1.5 else 60 if volume_ratio > 1.0 else 30)

            if patterns is None:
                patterns = {c[len('Pattern_'):]: bool(latest[c]) for c in data.columns if c.startswith('Pattern_')}
            bullish = ('bullish_flag', 'double_bottom', 'ascending_triangle')
            bearish = ('double_top', 'head_and_shoulders', 'descending_triangle')
            if any(patterns.get(p) for p in bullish):
                score_components.append(80)
            elif any(patterns.get(p) for p in bearish):
                score_components.append(30)
            else:
                score_components.append(50)

        except Exception as e:
            logger.warning(f"Error calculating technical score: {str(e)}")

        return float(np.mean(score_components)) if score_components else 50.0

    def calculate_momentum_score(self, data: pd.DataFrame) -> float:
        """
        Momentum score (0-100): a weighted average of rate-of-change across
        horizons, volatility and up-day streaks, normalised to stay within 0-100.
        """
        if len(data) < 20:
            return 50.0

        latest = data.iloc[-1]
        weighted = []  # (score, weight)

        try:
            roc_weights = {'1d': 0.4, '5d': 0.3, '10d': 0.2, '20d': 0.1}
            for period, weight in roc_weights.items():
                roc = latest.get(f'ROC_{period}', np.nan)
                if pd.isna(roc):
                    continue
                if period == '1d':
                    score = 90 if roc > 2 else 70 if roc > 0.5 else 60 if roc > 0 else 40 if roc > -0.5 else 20
                else:
                    score = 80 if roc > 5 else 60 if roc > 2 else 50 if roc > 0 else 30
                weighted.append((score, weight))

            vol = latest.get('Volatility_20d', np.nan)
            if pd.notna(vol):
                score = 80 if vol < 0.02 else 60 if vol < 0.04 else 40 if vol < 0.06 else 20
                weighted.append((score, 0.2))

            streak = [min(60 + d * 5, 90) for d in (2, 3, 4, 5) if latest.get(f'Consecutive_Up_{d}d', 0)]
            weighted.append((max(streak) if streak else 50, 0.3))

        except Exception as e:
            logger.warning(f"Error calculating momentum score: {str(e)}")

        total_weight = sum(w for _, w in weighted)
        if total_weight == 0:
            return 50.0
        return float(sum(s * w for s, w in weighted) / total_weight)

    def calculate_volume_score(self, data: pd.DataFrame) -> float:
        """Volume-based score (0-100)."""
        if len(data) < 20:
            return 50.0

        latest = data.iloc[-1]
        recent_data = data.tail(5)
        score_components = []

        try:
            volume_ratio = latest.get('Volume_Ratio', np.nan)
            if pd.notna(volume_ratio):
                score_components.append(90 if volume_ratio > 2.0 else 80 if volume_ratio > 1.5
                                        else 60 if volume_ratio > 1.0 else 40 if volume_ratio > 0.7 else 20)

            avg_volume = recent_data['Volume'].mean()
            if avg_volume > 0:
                slope = np.polyfit(range(len(recent_data)), recent_data['Volume'].values, 1)[0] / avg_volume
                score_components.append(80 if slope > 0.1 else 60 if slope > 0 else 40 if slope > -0.1 else 20)

            price_changes = recent_data['Close'].pct_change().dropna()
            volume_changes = recent_data['Volume'].pct_change().dropna()
            if len(price_changes) >= 3 and price_changes.std() > 0 and volume_changes.std() > 0:
                correlation = np.corrcoef(price_changes, volume_changes)[0, 1]
                if not np.isnan(correlation):
                    score_components.append(80 if correlation > 0.3 else 60 if correlation > 0
                                            else 40 if correlation > -0.3 else 20)

            if 'OBV' in data.columns and len(data) >= 10:
                obv_recent = data['OBV'].tail(10).fillna(0).values
                obv_trend = np.polyfit(range(len(obv_recent)), obv_recent, 1)[0]
                score_components.append(70 if obv_trend > 0 else 30)

        except Exception as e:
            logger.warning(f"Error calculating volume score: {str(e)}")

        return float(np.mean(score_components)) if score_components else 50.0

    def score_components(self, data: pd.DataFrame, patterns: Dict[str, bool] = None) -> Dict[str, float]:
        """Price-based component scores (technical, momentum, volume) for the latest row."""
        return {
            'technical_score': self.calculate_technical_score(data, patterns),
            'momentum_score': self.calculate_momentum_score(data),
            'volume_score': self.calculate_volume_score(data),
        }

    def describe_signals(self, data: pd.DataFrame) -> List[str]:
        """Plain-language notes on the notable signals in the latest row."""
        latest = data.iloc[-1]
        notes = []
        rsi = latest.get('RSI', np.nan)
        if pd.notna(rsi):
            if rsi < 30:
                notes.append(f"RSI {rsi:.0f}: oversold")
            elif rsi > 70:
                notes.append(f"RSI {rsi:.0f}: overbought")
        if latest.get('MACD_Cross_Up', 0):
            notes.append("MACD just crossed above its signal line")
        elif latest.get('MACD_Cross_Down', 0):
            notes.append("MACD just crossed below its signal line")
        bb = latest.get('BB_Position', np.nan)
        if pd.notna(bb) and bb < 0.1:
            notes.append("Trading near the lower Bollinger band")
        elif pd.notna(bb) and bb > 0.9:
            notes.append("Trading near the upper Bollinger band")
        volume_ratio = latest.get('Volume_Ratio', np.nan)
        if pd.notna(volume_ratio) and volume_ratio > 1.8:
            notes.append(f"Volume {volume_ratio:.1f}x its 20-day average")
        for period in (50, 200):
            distance = latest.get(f'Price_Distance_SMA_{period}', np.nan)
            if pd.notna(distance) and pd.notna(latest.get(f'SMA_{period}', np.nan)):
                side = 'above' if distance > 0 else 'below'
                if abs(distance) > 0.1:
                    notes.append(f"{abs(distance):.0%} {side} its {period}-day average")
        roc5 = latest.get('ROC_5d', np.nan)
        if pd.notna(roc5) and abs(roc5) > 8:
            notes.append(f"{roc5:+.1f}% over the last 5 days")
        for pattern in ('double_bottom', 'bullish_flag', 'ascending_triangle', 'double_top',
                        'head_and_shoulders', 'descending_triangle'):
            if latest.get(f'Pattern_{pattern}', False):
                notes.append(f"Chart pattern: {pattern.replace('_', ' ')}")
        return notes

    # -------------------------------------------------------------------- ML

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

    def save_models(self, path: Optional[str] = None) -> str:
        """Persist this pipeline's trained return models (one file per universe)."""
        path = path or self.model_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.predictor.save_models(path)
        return path

    def get_ml_prediction_score(self, symbol: str, data: pd.DataFrame) -> Tuple[float, float]:
        """
        ML probability (0-100) and model agreement (0-1) for one asset's latest row.
        Returns a neutral (50.0, 0.0) when no model is available.
        """
        if not self.ml_trained:
            return 50.0, 0.0
        try:
            prediction = self.predictor.predict(data.tail(1), model_name='ensemble')
            probability = float(prediction['probabilities'][0])
            individual = [float(p[0]) for p in prediction.get('individual_probabilities', {}).values()]
            confidence = max(0.0, 1.0 - float(np.std(individual)) * 4) if len(individual) > 1 else 0.7
            return probability * 100, confidence
        except Exception as e:
            logger.warning(f"Error getting ML prediction for {symbol}: {str(e)}")
            return 50.0, 0.0

    # ------------------------------------------------------------- sentiment

    def get_sentiment_score(self, symbol: str) -> Optional[float]:
        """Sentiment score (0-100), or None when disabled for this universe."""
        if not self.use_sentiment or self.weights.get('sentiment_score', 0) <= 0:
            return None
        try:
            sentiment_data = self.sentiment_analyzer.get_comprehensive_sentiment_score(
                symbol, self.data_collector
            )
            if sentiment_data:
                composite = sentiment_data.get('composite_score', 0)
                sentiment_score = (composite + 1) * 50
                confidence = sentiment_data.get('confidence', 0.5)
                return sentiment_score * confidence + 50 * (1 - confidence)
        except Exception as e:
            logger.warning(f"Error getting sentiment for {symbol}: {str(e)}")
        return 50.0

    # --------------------------------------------------------------- filters

    def apply_filters(self, symbol: str, data: pd.DataFrame, company_info: Dict = None) -> bool:
        """True if the asset passes this universe's price, liquidity and size filters."""
        if data.empty:
            return False

        try:
            current_price = data['Close'].iloc[-1]
            min_price = self.filters.get('min_price', 0) or 0
            max_price = self.filters.get('max_price', 0) or 0
            if current_price < min_price or (max_price > 0 and current_price > max_price):
                return False

            avg_volume = data['Volume'].tail(20).mean()
            if avg_volume < (self.filters.get('min_volume', 0) or 0):
                return False

            if self.filters.get('exclude_penny_stocks', False) and current_price < 5.0:
                return False

            min_cap = self.filters.get('min_market_cap', 0) or 0
            if company_info and company_info.get('market_cap') and company_info['market_cap'] < min_cap:
                return False

        except Exception as e:
            logger.warning(f"Error applying filters to {symbol}: {str(e)}")
            return False

        return True

    # --------------------------------------------------------------- ranking

    def asset_metadata(self, symbol: str, company_info: Optional[Dict]) -> Dict[str, str]:
        """Name and sector for display. Overridden for crypto."""
        info = company_info or {}
        return {'name': info.get('name') or symbol, 'sector': info.get('sector') or 'N/A'}

    def rank_stocks(self, symbols: List[str]) -> pd.DataFrame:
        """
        Score every asset that passes the filters.

        Returns:
            DataFrame with one row per asset, best composite score first
        """
        logger.info(f"Starting ranking for {len(symbols)} {self.universe} symbols...")
        prepared_data = self.fetch_and_prepare_data(symbols)
        self.last_prepared = prepared_data

        candidates, infos = {}, {}
        for symbol, data in prepared_data.items():
            infos[symbol] = self.data_collector.fetch_company_info(symbol)
            if self.apply_filters(symbol, data, infos[symbol]):
                candidates[symbol] = data

        if self.weights.get('ml_prediction', 0) > 0 or self.volatility_enabled:
            self.train_ml_models(prepared_data)

        if not candidates:
            logger.warning("No assets passed the filters")
            return pd.DataFrame()

        latest = pd.concat([d.tail(1).assign(Symbol=s) for s, d in candidates.items()])
        latest.index = list(candidates)

        probabilities = pd.Series(np.nan, index=latest.index)
        agreement = pd.Series(0.0, index=latest.index)
        if self.ml_trained:
            prediction = self.predictor.predict(latest)
            probabilities[:] = prediction['probabilities']
            individual = np.vstack(list(prediction['individual_probabilities'].values()))
            agreement[:] = np.clip(1 - individual.std(axis=0) * 4, 0, 1) if len(individual) > 1 else 0.7
        ml_scores = percentile_scores(probabilities) if self.ml_trained and len(latest) >= 5 \
            else probabilities.fillna(0.5) * 100

        vol = None
        if self.volatility.classifier is not None:
            vol = self.volatility.predict(latest)

        rows = []
        for symbol, data in candidates.items():
            try:
                scores = self.score_components(data)
                scores['ml_prediction'] = float(ml_scores[symbol]) if self.ml_trained else None
                scores['sentiment_score'] = self.get_sentiment_score(symbol)
                score = composite_score(scores, self.weights)
                last = data.iloc[-1]
                meta = self.asset_metadata(symbol, infos.get(symbol))
                current_vol = float(last['Volatility_20d'] * np.sqrt(self.periods_per_year)) \
                    if pd.notna(last.get('Volatility_20d', np.nan)) else np.nan

                rows.append({
                    'Symbol': symbol,
                    'Company_Name': meta['name'],
                    'Sector': meta['sector'],
                    'Asset_Class': self.universe,
                    'Current_Price': float(last['Close']),
                    'Daily_Change_Pct': float(last['Daily_Return'] * 100) if pd.notna(last['Daily_Return']) else 0.0,
                    'Volume': float(last['Volume']),
                    'Composite_Score': score,
                    'Technical_Score': scores['technical_score'],
                    'ML_Score': float(ml_scores[symbol]) if self.ml_trained else 50.0,
                    'ML_Probability': float(probabilities[symbol]) if self.ml_trained else np.nan,
                    'ML_Confidence': float(agreement[symbol]),
                    'Momentum_Score': scores['momentum_score'],
                    'Volume_Score': scores['volume_score'],
                    'Sentiment_Score': scores['sentiment_score'] if scores['sentiment_score'] is not None else np.nan,
                    'RSI': float(last.get('RSI', np.nan)),
                    'MACD': float(last.get('MACD', np.nan)),
                    'Volatility': current_vol,
                    'Vol_Forecast': float(vol.loc[symbol, 'forecast_vol']) if vol is not None else np.nan,
                    'Vol_Up_Probability': float(vol.loc[symbol, 'prob_vol_up']) if vol is not None else np.nan,
                    'Recommendation': recommendation_label(score, float(agreement[symbol])),
                    'Signals': self.describe_signals(data),
                    'Explanation': self.predictor.explain(data.tail(1)) if self.ml_trained else [],
                    'Horizon_Days': self.horizon,
                    'Data_Date': data.index[-1].strftime('%Y-%m-%d'),
                    'Analysis_Date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                })
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {str(e)}")

        if not rows:
            return pd.DataFrame()
        results = pd.DataFrame(rows).sort_values('Composite_Score', ascending=False).reset_index(drop=True)
        logger.info(f"Successfully analyzed {len(results)} assets")
        return results

    def get_top_10_recommendations(self, symbols: List[str] = None, top_n: int = None) -> Dict[str, Any]:
        """
        Rank the universe and build the suggested portfolio.

        Args:
            symbols: Symbols to analyze (defaults to the universe's list)
            top_n: Number of picks (defaults to ranking_config.top_picks)

        Returns:
            Dictionary with 'top_10' (picks with weights), 'full_rankings' and 'analysis_summary'
        """
        symbols = symbols or self.symbols
        if not symbols:
            raise ValueError("No symbols provided for analysis")
        top_n = top_n or self.ranking_config.get('top_picks', 10)

        rankings = self.rank_stocks(symbols)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if rankings.empty:
            return {
                'top_10': pd.DataFrame(), 'full_rankings': pd.DataFrame(),
                'analysis_summary': {
                    'universe': self.universe, 'total_analyzed': 0,
                    'total_symbols_attempted': len(symbols), 'analysis_date': now,
                    'average_composite_score': 0.0, 'top_score': 0.0, 'market_sentiment': 'Unknown',
                },
            }

        top = select_portfolio(rankings, top_n, sector_col='Sector', vol_col='Volatility',
                               max_per_sector=self.portfolio_config.get('max_per_sector', 0),
                               weighting=self.portfolio_config.get('weighting', 'equal'))
        ensemble = self.ml_performance.get('ensemble', {})
        analysis_summary = {
            'universe': self.universe,
            'label': self.label,
            'total_analyzed': len(rankings),
            'total_symbols_attempted': len(symbols),
            'analysis_date': now,
            'data_date': rankings['Data_Date'].max(),
            'horizon_days': self.horizon,
            'target': self.predictor.config['training'].get('target'),
            'average_composite_score': float(rankings['Composite_Score'].mean()),
            'top_score': float(rankings['Composite_Score'].max()),
            'market_sentiment': self._get_market_sentiment_summary(),
            'sector_distribution': top['Sector'].value_counts().to_dict(),
            'ml_models_used': [k for k in self.ml_performance if k != 'ensemble'] if self.ml_trained else [],
            'ml_test_accuracy': {k: v.get('test_accuracy') for k, v in self.ml_performance.items() if k != 'ensemble'},
            'model_quality': {k: v for k, v in ensemble.items() if k != 'reliability'},
            'calibration': ensemble.get('reliability', []),
            'volatility_model': self.volatility_performance,
            'top_features': [{'feature': f, 'importance': float(i)}
                             for f, i in self.predictor.get_feature_importance('xgboost', top_n=10)],
            'confidence_stats': {
                'avg_ml_confidence': float(top['ML_Confidence'].mean()),
                'high_confidence_picks': int((top['ML_Confidence'] > 0.7).sum()),
            },
        }
        return {'top_10': top, 'analysis_summary': analysis_summary, 'full_rankings': rankings}

    def _get_market_sentiment_summary(self) -> str:
        """Overall market tone from the benchmark's last daily move."""
        try:
            market_data = self.data_collector.fetch_market_data()
            if market_data and 'SPY' in market_data:
                change = market_data['SPY'].get('change_pct', 0)
                return "Bullish" if change > 1 else "Positive" if change > 0 else "Negative" if change > -1 else "Bearish"
        except Exception as e:
            logger.warning(f"Error getting market sentiment: {str(e)}")
        return "Neutral"

    def save_recommendations(self, recommendations: Dict[str, Any], filename: str = None) -> str:
        """Save the picks to CSV. Returns the path ('' on failure)."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"data/{self.universe}_recommendations_{timestamp}.csv"
        try:
            top = recommendations['top_10']
            if not top.empty:
                directory = os.path.dirname(filename)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                top.drop(columns=['Explanation'], errors='ignore').assign(
                    Signals=top['Signals'].map('; '.join) if 'Signals' in top else None
                ).to_csv(filename, index=False)
                logger.info(f"Recommendations saved to {filename}")
            return filename
        except Exception as e:
            logger.error(f"Error saving recommendations: {str(e)}")
            return ""
