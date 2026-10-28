"""
Stock ranking and prediction system to identify top 10 stocks.
"""

import logging
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.analysis.sentiment_analysis import SentimentAnalyzer
from src.analysis.technical_indicators import TechnicalAnalyzer
from src.data.collector import DataCollector, load_config, resolve_config_path
from src.data.preprocessor import DataPreprocessor
from src.models.evaluation import ModelEvaluator
from src.models.ml_models import StockPredictor
from src.utils.helpers import recommendation_label

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {
    'technical_score': 0.30,
    'ml_prediction': 0.25,
    'momentum_score': 0.20,
    'volume_score': 0.15,
    'sentiment_score': 0.10,
}

# Scores that are computed from price/volume history alone (usable in backtests)
PRICE_BASED_COMPONENTS = ('technical_score', 'momentum_score', 'volume_score')


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


class StockRanker:
    """
    Main ranking system that combines all analysis to select top 10 stocks.
    """

    def __init__(self, config_path: str = "config/config.yaml",
                 data_collector: Optional[DataCollector] = None):
        """
        Initialize the stock ranker.

        Args:
            config_path: Path to config.yaml (relative paths also resolve from the project root)
            data_collector: Optional collector to use instead of the live Yahoo Finance one
                (useful for tests, cached data, or other data sources)
        """
        self.config_path = resolve_config_path(config_path)
        self.config = load_config(config_path)

        # Initialize components
        self.data_collector = data_collector or DataCollector(config_path)
        self.preprocessor = DataPreprocessor()
        self.technical_analyzer = TechnicalAnalyzer(self.config.get('technical_analysis', {}))
        self.sentiment_analyzer = SentimentAnalyzer()
        self.predictor = StockPredictor(self.config.get('ml_config', {}))
        self.evaluator = ModelEvaluator()

        # Ranking configuration
        self.ranking_config = self.config.get('ranking_config', {})
        self.weights = {**DEFAULT_WEIGHTS, **self.ranking_config.get('weights', {})}
        self.filters = self.ranking_config.get('filters', {})
        self.use_sentiment = self.ranking_config.get('use_sentiment', True)
        self.target_threshold = self.config.get('ml_config', {}).get('training', {}).get('target_threshold', 0.0)

        self.ml_trained = False
        self.ml_performance: Dict[str, Dict[str, Any]] = {}

        logger.info("Stock Ranker initialized successfully")

    # ------------------------------------------------------------------ data

    def prepare_symbol_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        """
        Run the full feature pipeline on one stock's raw OHLCV data.

        Every feature at date t uses only data up to t. The targets
        (Future_Return, Target_Up) look one day ahead and are NaN on the last row.
        """
        data = self.preprocessor.clean_stock_data(raw)
        data = self.preprocessor.add_basic_features(data)
        data = self.preprocessor.add_moving_averages(data)
        data = self.preprocessor.add_momentum_features(data)
        data = self.preprocessor.add_pattern_features(data)
        data = self.preprocessor.add_support_resistance(data)
        data = self.technical_analyzer.calculate_all_indicators(data)
        data = self.preprocessor.create_target_variable(data, threshold=self.target_threshold)
        return data

    def fetch_and_prepare_data(self, symbols: List[str], period: str = None) -> Dict[str, pd.DataFrame]:
        """
        Fetch and prepare data for all symbols.

        Args:
            symbols: List of stock symbols
            period: History to fetch (defaults to stock_config.timeframe)

        Returns:
            Dictionary of prepared DataFrames
        """
        logger.info(f"Fetching data for {len(symbols)} symbols...")
        period = period or self.config.get('stock_config', {}).get('timeframe', '2y')
        raw_data = self.data_collector.fetch_multiple_stocks(symbols, period=period)

        prepared_data = {}
        for symbol, data in raw_data.items():
            try:
                if data is None or data.empty:
                    logger.warning(f"No data available for {symbol}")
                    continue
                prepared_data[symbol] = self.prepare_symbol_data(data)
            except Exception as e:
                logger.error(f"Error preparing data for {symbol}: {str(e)}")

        logger.info(f"Successfully prepared data for {len(prepared_data)} symbols")
        return prepared_data

    # ---------------------------------------------------------------- scores

    def calculate_technical_score(self, data: pd.DataFrame, patterns: Dict[str, bool] = None) -> float:
        """
        Calculate technical analysis score for a stock (0-100) from its latest row.

        Args:
            data: Prepared stock data
            patterns: Chart patterns for the latest window; read from the
                ``Pattern_*`` columns of the latest row when not given
        """
        if data.empty:
            return 0.0

        latest = data.iloc[-1]
        score_components = []

        try:
            # RSI (oversold conditions score higher)
            rsi = latest.get('RSI', np.nan)
            if pd.notna(rsi):
                if rsi < 30:
                    score_components.append(90)
                elif rsi < 50:
                    score_components.append(70)
                elif rsi < 70:
                    score_components.append(50)
                else:
                    score_components.append(20)

            # MACD
            if pd.notna(latest.get('MACD', np.nan)) and pd.notna(latest.get('MACD_Signal', np.nan)):
                macd_score = 80 if latest['MACD'] > latest['MACD_Signal'] else 20
                if latest.get('MACD_Cross_Up', 0):
                    macd_score += 20
                score_components.append(min(macd_score, 100))

            # Bollinger Bands position
            bb_position = latest.get('BB_Position', np.nan)
            if pd.notna(bb_position):
                if bb_position < 0.2:
                    score_components.append(90)
                elif bb_position < 0.5:
                    score_components.append(70)
                elif bb_position < 0.8:
                    score_components.append(50)
                else:
                    score_components.append(20)

            # Price vs moving averages
            sma_scores = [80 if latest[f'Price_Above_SMA_{p}'] else 20
                          for p in (20, 50)
                          if f'Price_Above_SMA_{p}' in latest and pd.notna(latest.get(f'SMA_{p}', np.nan))]
            if sma_scores:
                score_components.append(np.mean(sma_scores))

            # Volume confirmation
            volume_ratio = latest.get('Volume_Ratio', np.nan)
            if pd.notna(volume_ratio):
                score_components.append(80 if volume_ratio > 1.5 else 60 if volume_ratio > 1.0 else 30)

            # Chart patterns
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
        Calculate momentum score for a stock (0-100).

        A weighted average of rate-of-change across horizons, volatility and
        up-day streaks; weights are normalised so the score stays within 0-100.
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

            # Lower volatility is preferred for momentum
            vol = latest.get('Volatility_20d', np.nan)
            if pd.notna(vol):
                score = 80 if vol < 0.02 else 60 if vol < 0.04 else 40 if vol < 0.06 else 20
                weighted.append((score, 0.2))

            # Consecutive up days
            streak = [min(60 + d * 5, 90) for d in (2, 3, 4, 5) if latest.get(f'Consecutive_Up_{d}d', 0)]
            weighted.append((max(streak) if streak else 50, 0.3))

        except Exception as e:
            logger.warning(f"Error calculating momentum score: {str(e)}")

        total_weight = sum(w for _, w in weighted)
        if total_weight == 0:
            return 50.0
        return float(sum(s * w for s, w in weighted) / total_weight)

    def calculate_volume_score(self, data: pd.DataFrame) -> float:
        """
        Calculate volume-based score for a stock (0-100).
        """
        if len(data) < 20:
            return 50.0

        latest = data.iloc[-1]
        recent_data = data.tail(5)
        score_components = []

        try:
            # Current volume vs average
            volume_ratio = latest.get('Volume_Ratio', np.nan)
            if pd.notna(volume_ratio):
                if volume_ratio > 2.0:
                    score_components.append(90)
                elif volume_ratio > 1.5:
                    score_components.append(80)
                elif volume_ratio > 1.0:
                    score_components.append(60)
                elif volume_ratio > 0.7:
                    score_components.append(40)
                else:
                    score_components.append(20)

            # Volume trend over the last 5 days (rising volume scores higher)
            avg_volume = recent_data['Volume'].mean()
            if avg_volume > 0:
                slope = np.polyfit(range(len(recent_data)), recent_data['Volume'].values, 1)[0] / avg_volume
                score_components.append(80 if slope > 0.1 else 60 if slope > 0 else 40 if slope > -0.1 else 20)

            # Price-volume relationship (price up with volume up is good)
            price_changes = recent_data['Close'].pct_change().dropna()
            volume_changes = recent_data['Volume'].pct_change().dropna()
            if len(price_changes) >= 3 and price_changes.std() > 0 and volume_changes.std() > 0:
                correlation = np.corrcoef(price_changes, volume_changes)[0, 1]
                if not np.isnan(correlation):
                    score_components.append(80 if correlation > 0.3 else 60 if correlation > 0
                                            else 40 if correlation > -0.3 else 20)

            # On-Balance Volume trend
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

    # -------------------------------------------------------------------- ML

    def train_ml_models(self, prepared_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, Any]]:
        """
        Train the ML models once on the pooled history of every stock.

        Args:
            prepared_data: Output of :meth:`fetch_and_prepare_data`

        Returns:
            Model performances (empty if there was not enough data)
        """
        self.ml_trained = False
        frames = []
        for symbol, data in prepared_data.items():
            frame = data.dropna(subset=['Target_Up']).copy()
            frame['Symbol'] = symbol
            frames.append(frame)
        if not frames:
            return {}

        pooled = pd.concat(frames)
        try:
            self.ml_performance = self.predictor.train_evaluate_and_refit(pooled)
            self.ml_trained = bool(self.ml_performance)
        except ValueError as e:
            logger.warning(f"Skipping ML models: {e}")
            self.ml_performance = {}
        return self.ml_performance

    def get_ml_prediction_score(self, symbol: str, data: pd.DataFrame) -> Tuple[float, float]:
        """
        Get the ML score for a stock's latest row.

        Uses the models trained by :meth:`train_ml_models`. Returns a neutral
        (50.0, 0.0) when no model is available.

        Returns:
            Tuple of (prediction_score 0-100, confidence 0-1 from model agreement)
        """
        if not self.ml_trained:
            return 50.0, 0.0
        try:
            prediction = self.predictor.predict(data.tail(1), model_name='ensemble')
            probability = float(prediction['probabilities'][0])
            individual = [float(p[0]) for p in prediction.get('individual_probabilities', {}).values()]
            if len(individual) > 1:
                confidence = max(0.0, 1.0 - float(np.std(individual)) * 4)
            else:
                confidence = 0.7
            return probability * 100, confidence
        except Exception as e:
            logger.warning(f"Error getting ML prediction for {symbol}: {str(e)}")
            return 50.0, 0.0

    # ------------------------------------------------------------- sentiment

    def get_sentiment_score(self, symbol: str) -> Optional[float]:
        """
        Get sentiment score for a stock (0-100), or None when disabled.
        """
        if not self.use_sentiment or self.weights.get('sentiment_score', 0) <= 0:
            return None
        try:
            sentiment_data = self.sentiment_analyzer.get_comprehensive_sentiment_score(
                symbol, self.data_collector
            )
            if sentiment_data:
                composite = sentiment_data.get('composite_score', 0)
                sentiment_score = (composite + 1) * 50  # -1..1 -> 0..100
                confidence = sentiment_data.get('confidence', 0.5)
                return sentiment_score * confidence + 50 * (1 - confidence)
        except Exception as e:
            logger.warning(f"Error getting sentiment for {symbol}: {str(e)}")
        return 50.0

    # --------------------------------------------------------------- filters

    def apply_filters(self, symbol: str, data: pd.DataFrame, company_info: Dict = None) -> bool:
        """
        Apply filtering criteria to stock.

        Returns:
            True if stock passes filters
        """
        if data.empty:
            return False

        try:
            current_price = data['Close'].iloc[-1]
            min_price = self.filters.get('min_price', 5.0)
            max_price = self.filters.get('max_price', 1000.0)
            if max_price and max_price > 0 and current_price > max_price:
                logger.debug(f"{symbol} filtered out: price ${current_price:.2f}")
                return False
            if current_price < min_price:
                logger.debug(f"{symbol} filtered out: price ${current_price:.2f}")
                return False

            avg_volume = data['Volume'].tail(20).mean()
            if avg_volume < self.filters.get('min_volume', 1000000):
                logger.debug(f"{symbol} filtered out: low volume {avg_volume:,.0f}")
                return False

            if self.filters.get('exclude_penny_stocks', True) and current_price < 5.0:
                logger.debug(f"{symbol} filtered out: penny stock")
                return False

            min_cap = self.filters.get('min_market_cap', 1e9)
            if company_info and company_info.get('market_cap') and company_info['market_cap'] < min_cap:
                logger.debug(f"{symbol} filtered out: small market cap")
                return False

        except Exception as e:
            logger.warning(f"Error applying filters to {symbol}: {str(e)}")
            return False

        return True

    # --------------------------------------------------------------- ranking

    def rank_stocks(self, symbols: List[str]) -> pd.DataFrame:
        """
        Rank all stocks by composite score.

        Args:
            symbols: List of stock symbols to analyze

        Returns:
            DataFrame with every stock that passed the filters, best first
        """
        logger.info(f"Starting stock ranking for {len(symbols)} symbols...")
        prepared_data = self.fetch_and_prepare_data(symbols)

        candidates = {}
        company_infos = {}
        for symbol, data in prepared_data.items():
            company_infos[symbol] = self.data_collector.fetch_company_info(symbol)
            if self.apply_filters(symbol, data, company_infos[symbol]):
                candidates[symbol] = data

        # ML is trained on the whole universe's history, then applied per stock
        if self.weights.get('ml_prediction', 0) > 0:
            self.train_ml_models(prepared_data)

        ranking_results = []
        for symbol, data in candidates.items():
            try:
                logger.info(f"Analyzing {symbol}...")
                company_info = company_infos.get(symbol) or {}

                scores = self.score_components(data)
                ml_score, ml_confidence = self.get_ml_prediction_score(symbol, data)
                scores['ml_prediction'] = ml_score if self.ml_trained else None
                scores['sentiment_score'] = self.get_sentiment_score(symbol)

                score = composite_score(scores, self.weights)
                latest = data.iloc[-1]

                ranking_results.append({
                    'Symbol': symbol,
                    'Company_Name': company_info.get('name') or 'N/A',
                    'Sector': company_info.get('sector') or 'N/A',
                    'Current_Price': latest['Close'],
                    'Daily_Change_Pct': latest['Daily_Return'] * 100 if pd.notna(latest['Daily_Return']) else 0.0,
                    'Volume': latest['Volume'],
                    'Composite_Score': score,
                    'Technical_Score': scores['technical_score'],
                    'ML_Score': ml_score,
                    'ML_Confidence': ml_confidence,
                    'Momentum_Score': scores['momentum_score'],
                    'Volume_Score': scores['volume_score'],
                    'Sentiment_Score': scores['sentiment_score'] if scores['sentiment_score'] is not None else np.nan,
                    'RSI': latest.get('RSI', np.nan),
                    'MACD': latest.get('MACD', np.nan),
                    'Recommendation': recommendation_label(score, ml_confidence),
                    'Data_Date': data.index[-1].strftime('%Y-%m-%d') if hasattr(data.index[-1], 'strftime') else str(data.index[-1]),
                    'Analysis_Date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                })

            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {str(e)}")

        if not ranking_results:
            logger.warning("No stocks passed analysis")
            return pd.DataFrame()

        results_df = pd.DataFrame(ranking_results).sort_values('Composite_Score', ascending=False)
        results_df = results_df.reset_index(drop=True)
        logger.info(f"Successfully analyzed {len(results_df)} stocks")
        return results_df

    def get_top_10_recommendations(self, symbols: List[str] = None, top_n: int = None) -> Dict[str, Any]:
        """
        Get the top stock recommendations.

        Args:
            symbols: List of symbols to analyze (uses config default if None)
            top_n: How many picks to return (defaults to ranking_config.top_picks)

        Returns:
            Dictionary with 'top_10', 'analysis_summary' and 'full_rankings'
        """
        if symbols is None:
            symbols = self.config.get('stock_config', {}).get('symbols', [])
        if not symbols:
            raise ValueError("No symbols provided for analysis")
        top_n = top_n or self.ranking_config.get('top_picks', 10)

        logger.info("Generating top stock recommendations...")
        rankings = self.rank_stocks(symbols)

        if rankings.empty:
            return {
                'top_10': pd.DataFrame(),
                'full_rankings': pd.DataFrame(),
                'analysis_summary': {
                    'total_analyzed': 0,
                    'total_symbols_attempted': len(symbols),
                    'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'average_composite_score': 0.0,
                    'top_score': 0.0,
                    'market_sentiment': 'Unknown',
                },
            }

        top_10 = rankings.head(top_n)
        analysis_summary = {
            'total_analyzed': len(rankings),
            'total_symbols_attempted': len(symbols),
            'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'average_composite_score': rankings['Composite_Score'].mean(),
            'top_score': rankings['Composite_Score'].max(),
            'market_sentiment': self._get_market_sentiment_summary(),
            'sector_distribution': top_10['Sector'].value_counts().to_dict(),
            'ml_models_used': list(self.ml_performance.keys()) if self.ml_trained else [],
            'ml_test_accuracy': {k: v.get('test_accuracy') for k, v in self.ml_performance.items()},
            'confidence_stats': {
                'avg_ml_confidence': top_10['ML_Confidence'].mean(),
                'high_confidence_picks': int((top_10['ML_Confidence'] > 0.7).sum()),
            },
        }

        logger.info(f"Top {top_n} recommendations generated. Best score: {analysis_summary['top_score']:.1f}")
        return {'top_10': top_10, 'analysis_summary': analysis_summary, 'full_rankings': rankings}

    def _get_market_sentiment_summary(self) -> str:
        """Overall market sentiment from the S&P 500 ETF's last daily move."""
        try:
            market_data = self.data_collector.fetch_market_data()
            if market_data and 'SPY' in market_data:
                spy_change = market_data['SPY'].get('change_pct', 0)
                if spy_change > 1:
                    return "Bullish"
                if spy_change > 0:
                    return "Positive"
                if spy_change > -1:
                    return "Negative"
                return "Bearish"
        except Exception as e:
            logger.warning(f"Error getting market sentiment: {str(e)}")
        return "Neutral"

    def save_recommendations(self, recommendations: Dict[str, Any], filename: str = None) -> str:
        """
        Save recommendations to CSV file.

        Returns:
            Path to saved file ('' on failure)
        """
        import os
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"data/stock_recommendations_{timestamp}.csv"
        try:
            top_10 = recommendations['top_10']
            if not top_10.empty:
                directory = os.path.dirname(filename)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                top_10.to_csv(filename, index=False)
                logger.info(f"Recommendations saved to {filename}")
            return filename
        except Exception as e:
            logger.error(f"Error saving recommendations: {str(e)}")
            return ""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ranker = StockRanker()
    test_symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM', 'V', 'UNH']
    recommendations = ranker.get_top_10_recommendations(test_symbols)
    print(recommendations['top_10'][['Symbol', 'Composite_Score', 'Recommendation']])
