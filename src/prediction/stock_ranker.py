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
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from src.analysis.technical_indicators import TechnicalAnalyzer
from src.data.collector import PROJECT_ROOT, DataCollector, load_config, resolve_config_path
from src.data.preprocessor import DataPreprocessor
from src.models.volatility import VolatilityForecaster
from src.prediction.features import FeaturesMixin
from src.prediction.portfolio import select_portfolio
from src.prediction.scoring import (DEFAULT_WEIGHTS, ScoringMixin, composite_score, percentile_scores,
                                    recommendation_label)
from src.prediction.training import TrainingMixin, any_feature_label

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)


DEFAULT_UNIVERSES = {
    'stocks': {
        'label': 'US Stocks', 'symbols': [], 'timeframe': '2y', 'periods_per_year': 252,
        'long_term_horizon': 21,
        'filters': {'min_price': 5.0, 'max_price': 0, 'min_volume': 1_000_000,
                    'min_market_cap': 1e9, 'exclude_penny_stocks': True},
        'portfolio': {'max_per_sector': 3, 'weighting': 'inverse_volatility'},
    },
    'crypto': {
        'label': 'Crypto', 'symbols': [], 'timeframe': '2y', 'periods_per_year': 365,
        'long_term_horizon': 30,
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


class StockRanker(FeaturesMixin, ScoringMixin, TrainingMixin):
    """
    Shared ranking pipeline. Use :func:`src.prediction.pipelines.create_pipeline`
    to get the stock or crypto version.
    """

    asset_class = 'stocks'
    # Cross-sectional model: market factor (None = universe average) and momentum style
    market_symbol: Optional[str] = None
    momentum_style = 'long'

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
        self.predictor = self.new_predictor()

        vol_cfg = self.config.get('volatility', {})
        self.volatility_enabled = vol_cfg.get('enabled', True)
        self.volatility = VolatilityForecaster(horizon=vol_cfg.get('horizon', 5),
                                               periods_per_year=self.periods_per_year)

        # Ranking configuration
        self.ranking_config = self.config.get('ranking_config', {})
        self.weights = {**DEFAULT_WEIGHTS, **self.ranking_config.get('weights', {})}
        self.filters = self.universe_config['filters']
        self.portfolio_config = self.universe_config['portfolio']
        self.target_threshold = self.config.get('ml_config', {}).get('training', {}).get('target_threshold', 0.0)

        self.ml_trained = False
        self.ml_performance: Dict[str, Dict[str, Any]] = {}
        self.volatility_performance: Dict[str, Any] = {}
        self.long_predictor = None
        self.long_performance: Dict[str, Any] = {}
        self.last_prepared: Dict[str, pd.DataFrame] = {}
        # True: rank with the models already loaded (import_models) instead of training new ones
        self.reuse_models = False

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
    def long_horizon(self) -> Optional[int]:
        """Rows ahead for the long-term model (about a month); None turns it off."""
        value = self.universe_config.get('long_term_horizon')
        return int(value) if value and self.model_kind == 'cross_section' else None

    @property
    def model_kind(self) -> str:
        return self.config.get('ml_config', {}).get('model', 'cross_section')


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


    # -------------------------------------------------------------------- ML


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
        if hasattr(self.data_collector, 'reset_run_sources'):
            self.data_collector.reset_run_sources()
        prepared_data = self.fetch_and_prepare_data(symbols)
        self.last_prepared = prepared_data

        candidates, infos = {}, {}
        for symbol, data in prepared_data.items():
            infos[symbol] = self.data_collector.fetch_company_info(symbol)
            if self.apply_filters(symbol, data, infos[symbol]):
                candidates[symbol] = data

        if self.reuse_models:
            self.check_model_features(prepared_data)
        elif self.weights.get('ml_prediction', 0) > 0 or self.volatility_enabled:
            self.train_ml_models(prepared_data)

        if not candidates:
            logger.warning("No assets passed the filters")
            return pd.DataFrame()

        latest = pd.concat([d.tail(1).assign(Symbol=s) for s, d in candidates.items()])
        latest.index = list(candidates)

        probabilities = pd.Series(np.nan, index=latest.index)
        ranking = pd.Series(np.nan, index=latest.index)
        agreement = pd.Series(0.0, index=latest.index)
        if self.ml_trained:
            prediction = self.predictor.predict(latest)
            probabilities[:] = prediction['probabilities']
            # Rank on the model's own score when it has one (calibration must never reorder assets)
            ranking[:] = prediction.get('scores', prediction['probabilities'])
            individual = np.vstack(list(prediction['individual_probabilities'].values()))
            agreement[:] = np.clip(1 - individual.std(axis=0) * 4, 0, 1) if len(individual) > 1 else 0.7
        ml_scores = percentile_scores(ranking) if self.ml_trained and len(latest) >= 5 \
            else probabilities.fillna(0.5) * 100

        vol = None
        if self.volatility.classifier is not None:
            vol = self.volatility.predict(latest)

        long_scores = pd.Series(np.nan, index=latest.index)
        long_probabilities = pd.Series(np.nan, index=latest.index)
        if self.train_long_term(prepared_data):
            prediction = self.long_predictor.predict(latest)
            long_probabilities[:] = prediction['probabilities']
            if len(latest) >= 5:
                long_scores = percentile_scores(pd.Series(prediction['scores'], index=latest.index))

        rows = []
        for symbol, data in candidates.items():
            try:
                scores = self.score_components(data)
                scores['ml_prediction'] = float(ml_scores[symbol]) if self.ml_trained else None
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
                    'RSI': float(last.get('RSI', np.nan)),
                    'MACD': float(last.get('MACD', np.nan)),
                    'Volatility': current_vol,
                    'Vol_Forecast': float(vol.loc[symbol, 'forecast_vol']) if vol is not None else np.nan,
                    'Vol_Up_Probability': float(vol.loc[symbol, 'prob_vol_up']) if vol is not None else np.nan,
                    'Long_Score': float(long_scores[symbol]),
                    'Long_Probability': float(long_probabilities[symbol]),
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
            'long_term': self.long_term_summary(),
            # Where this analysis's prices came from: Yahoo Finance, or a fallback when it failed
            'data_sources': dict(getattr(self.data_collector, 'run_sources', {}) or {}) or None,
            'model_kind': getattr(self.predictor, 'kind', 'legacy'),
            'feature_count': len(self.predictor.feature_columns),
            'top_features': [{'feature': f, 'label': any_feature_label(f), 'importance': float(i)}
                             for f, i in self.predictor.get_feature_importance(
                                 'ridge' if self.model_kind == 'cross_section' else 'xgboost', top_n=10)],
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
