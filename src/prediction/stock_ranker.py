"""
Stock ranking and prediction system to identify top 10 stocks.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
import logging
from datetime import datetime, timedelta
import warnings
import yaml

# Import our modules
from src.data.collector import DataCollector
from src.data.preprocessor import DataPreprocessor
from src.analysis.technical_indicators import TechnicalAnalyzer
from src.analysis.sentiment_analysis import SentimentAnalyzer
from src.models.ml_models import StockPredictor
from src.models.evaluation import ModelEvaluator

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)


class StockRanker:
    """
    Main ranking system that combines all analysis to select top 10 stocks.
    """
    
    def __init__(self, config_path: str = "config/config.yaml"):
        """Initialize the stock ranker."""
        self.config = self._load_config(config_path)
        
        # Initialize components
        self.data_collector = DataCollector(config_path)
        self.preprocessor = DataPreprocessor()
        self.technical_analyzer = TechnicalAnalyzer(self.config.get('technical_analysis', {}))
        self.sentiment_analyzer = SentimentAnalyzer()
        self.predictor = StockPredictor(self.config.get('ml_config', {}))
        self.evaluator = ModelEvaluator()
        
        # Ranking configuration
        self.ranking_config = self.config.get('ranking_config', {})
        self.weights = self.ranking_config.get('weights', {})
        self.filters = self.ranking_config.get('filters', {})
        
        logger.info("Stock Ranker initialized successfully")
    
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file."""
        try:
            with open(config_path, 'r') as file:
                return yaml.safe_load(file)
        except FileNotFoundError:
            logger.warning(f"Config file not found: {config_path}. Using defaults.")
            return {}
    
    def fetch_and_prepare_data(self, symbols: List[str]) -> Dict[str, pd.DataFrame]:
        """
        Fetch and prepare data for all symbols.
        
        Args:
            symbols: List of stock symbols
        
        Returns:
            Dictionary of prepared DataFrames
        """
        logger.info(f"Fetching data for {len(symbols)} symbols...")
        
        # Fetch raw data
        raw_data = self.data_collector.fetch_multiple_stocks(
            symbols, 
            period=self.config.get('stock_config', {}).get('timeframe', '6mo')
        )
        
        prepared_data = {}
        
        for symbol, data in raw_data.items():
            try:
                if data is None or data.empty:
                    logger.warning(f"No data available for {symbol}")
                    continue
                
                # Clean and preprocess data
                clean_data = self.preprocessor.clean_stock_data(data)
                
                # Add basic features
                clean_data = self.preprocessor.add_basic_features(clean_data)
                clean_data = self.preprocessor.add_moving_averages(clean_data)
                clean_data = self.preprocessor.add_momentum_features(clean_data)
                clean_data = self.preprocessor.add_pattern_features(clean_data)
                clean_data = self.preprocessor.add_support_resistance(clean_data)
                
                # Add technical indicators
                clean_data = self.technical_analyzer.calculate_all_indicators(clean_data)
                
                # Create target variables
                clean_data = self.preprocessor.create_target_variable(clean_data)
                
                prepared_data[symbol] = clean_data
                
            except Exception as e:
                logger.error(f"Error preparing data for {symbol}: {str(e)}")
                continue
        
        logger.info(f"Successfully prepared data for {len(prepared_data)} symbols")
        return prepared_data
    
    def calculate_technical_score(self, data: pd.DataFrame) -> float:
        """
        Calculate technical analysis score for a stock.
        
        Args:
            data: Prepared stock data
        
        Returns:
            Technical score (0-100)
        """
        if data.empty:
            return 0.0
        
        latest = data.iloc[-1]
        score_components = []
        
        try:
            # RSI Score (oversold conditions are good for buying)
            if 'RSI' in latest:
                rsi = latest['RSI']
                if rsi < 30:
                    rsi_score = 90  # Oversold - high score
                elif rsi < 50:
                    rsi_score = 70
                elif rsi < 70:
                    rsi_score = 50
                else:
                    rsi_score = 20  # Overbought - low score
                score_components.append(rsi_score)
            
            # MACD Score
            if 'MACD' in latest and 'MACD_Signal' in latest:
                macd_bullish = latest['MACD'] > latest['MACD_Signal']
                macd_cross_up = latest.get('MACD_Cross_Up', 0)
                
                macd_score = 80 if macd_bullish else 20
                if macd_cross_up:
                    macd_score += 20
                
                score_components.append(min(macd_score, 100))
            
            # Bollinger Bands Score
            if 'BB_Position' in latest:
                bb_position = latest['BB_Position']
                if bb_position < 0.2:
                    bb_score = 90  # Near lower band - good for buying
                elif bb_position < 0.5:
                    bb_score = 70
                elif bb_position < 0.8:
                    bb_score = 50
                else:
                    bb_score = 20  # Near upper band
                score_components.append(bb_score)
            
            # Moving Average Score
            sma_scores = []
            for period in [20, 50]:
                if f'Price_Above_SMA_{period}' in latest:
                    if latest[f'Price_Above_SMA_{period}']:
                        sma_scores.append(80)
                    else:
                        sma_scores.append(20)
            
            if sma_scores:
                score_components.append(np.mean(sma_scores))
            
            # Volume Score
            if 'Volume_Ratio' in latest:
                volume_ratio = latest['Volume_Ratio']
                if volume_ratio > 1.5:
                    volume_score = 80  # High volume confirmation
                elif volume_ratio > 1.0:
                    volume_score = 60
                else:
                    volume_score = 30
                score_components.append(volume_score)
            
            # Pattern Score
            pattern_columns = [col for col in data.columns if col.startswith('Pattern_')]
            bullish_patterns = ['Pattern_bullish_flag', 'Pattern_double_bottom', 'Pattern_ascending_triangle']
            pattern_score = 50  # Neutral default
            
            for pattern in bullish_patterns:
                if pattern in pattern_columns and latest.get(pattern, 0):
                    pattern_score = 80
                    break
            
            score_components.append(pattern_score)
            
        except Exception as e:
            logger.warning(f"Error calculating technical score: {str(e)}")
        
        if not score_components:
            return 50.0  # Neutral score if no components calculated
        
        return np.mean(score_components)
    
    def calculate_momentum_score(self, data: pd.DataFrame) -> float:
        """
        Calculate momentum score for a stock.
        
        Args:
            data: Prepared stock data
        
        Returns:
            Momentum score (0-100)
        """
        if len(data) < 20:
            return 50.0
        
        latest = data.iloc[-1]
        score_components = []
        
        try:
            # Price momentum (various timeframes)
            for period in ['1d', '5d', '10d', '20d']:
                roc_col = f'ROC_{period}'
                if roc_col in latest:
                    roc = latest[roc_col]
                    if period == '1d':
                        # Recent momentum is most important
                        if roc > 2:
                            score = 90
                        elif roc > 0.5:
                            score = 70
                        elif roc > 0:
                            score = 60
                        elif roc > -0.5:
                            score = 40
                        else:
                            score = 20
                        score_components.append(score * 0.4)  # High weight for recent momentum
                    else:
                        # Longer-term momentum
                        weight = 0.3 if period == '5d' else 0.2 if period == '10d' else 0.1
                        if roc > 5:
                            score = 80
                        elif roc > 2:
                            score = 60
                        elif roc > 0:
                            score = 50
                        else:
                            score = 30
                        score_components.append(score * weight)
            
            # Volatility consideration (lower volatility is better for momentum)
            if 'Volatility_20d' in latest:
                vol = latest['Volatility_20d']
                if vol < 0.02:  # Low volatility
                    vol_score = 80
                elif vol < 0.04:
                    vol_score = 60
                elif vol < 0.06:
                    vol_score = 40
                else:
                    vol_score = 20
                score_components.append(vol_score * 0.2)
            
            # Consecutive up days
            consecutive_scores = []
            for days in [2, 3, 4, 5]:
                col = f'Consecutive_Up_{days}d'
                if col in latest and latest[col]:
                    consecutive_scores.append(min(60 + days * 5, 90))
            
            if consecutive_scores:
                score_components.append(max(consecutive_scores) * 0.3)
            
        except Exception as e:
            logger.warning(f"Error calculating momentum score: {str(e)}")
        
        if not score_components:
            return 50.0
        
        return min(sum(score_components), 100)
    
    def calculate_volume_score(self, data: pd.DataFrame) -> float:
        """
        Calculate volume-based score for a stock.
        
        Args:
            data: Prepared stock data
        
        Returns:
            Volume score (0-100)
        """
        if len(data) < 20:
            return 50.0
        
        latest = data.iloc[-1]
        recent_data = data.tail(5)
        
        score_components = []
        
        try:
            # Current volume vs average
            if 'Volume_Ratio' in latest:
                volume_ratio = latest['Volume_Ratio']
                if volume_ratio > 2.0:
                    score_components.append(90)  # Very high volume
                elif volume_ratio > 1.5:
                    score_components.append(80)  # High volume
                elif volume_ratio > 1.0:
                    score_components.append(60)  # Above average
                elif volume_ratio > 0.7:
                    score_components.append(40)  # Below average
                else:
                    score_components.append(20)  # Very low volume
            
            # Volume trend (increasing volume is good)
            if 'Volume' in recent_data.columns:
                volume_trend = np.polyfit(range(len(recent_data)), recent_data['Volume'], 1)[0]
                avg_volume = recent_data['Volume'].mean()
                volume_trend_normalized = volume_trend / avg_volume if avg_volume > 0 else 0
                
                if volume_trend_normalized > 0.1:
                    score_components.append(80)
                elif volume_trend_normalized > 0:
                    score_components.append(60)
                elif volume_trend_normalized > -0.1:
                    score_components.append(40)
                else:
                    score_components.append(20)
            
            # Price-Volume relationship (price up with volume up is good)
            if len(recent_data) >= 2:
                price_changes = recent_data['Close'].pct_change().dropna()
                volume_changes = recent_data['Volume'].pct_change().dropna()
                
                if len(price_changes) >= 2 and len(volume_changes) >= 2:
                    correlation = np.corrcoef(price_changes, volume_changes)[0, 1]
                    if not np.isnan(correlation):
                        if correlation > 0.3:
                            score_components.append(80)  # Good price-volume relationship
                        elif correlation > 0:
                            score_components.append(60)
                        elif correlation > -0.3:
                            score_components.append(40)
                        else:
                            score_components.append(20)  # Poor relationship
            
            # On-Balance Volume trend
            if 'OBV' in data.columns and len(data) >= 10:
                obv_recent = data['OBV'].tail(10)
                obv_trend = np.polyfit(range(len(obv_recent)), obv_recent, 1)[0]
                
                if obv_trend > 0:
                    score_components.append(70)  # Positive OBV trend
                else:
                    score_components.append(30)  # Negative OBV trend
            
        except Exception as e:
            logger.warning(f"Error calculating volume score: {str(e)}")
        
        if not score_components:
            return 50.0
        
        return np.mean(score_components)
    
    def get_ml_prediction_score(self, symbol: str, data: pd.DataFrame) -> Tuple[float, float]:
        """
        Get machine learning prediction score.
        
        Args:
            symbol: Stock symbol
            data: Prepared stock data
        
        Returns:
            Tuple of (prediction_score, confidence)
        """
        try:
            if len(data) < 50:
                return 50.0, 0.0
            
            # Train models on historical data
            train_data = data[:-1]  # Use all but last day for training
            test_data = data.tail(1)  # Use last day for prediction
            
            # Quick training with limited data
            performances = self.predictor.train_all_models(train_data)
            
            if not performances:
                return 50.0, 0.0
            
            # Make ensemble prediction
            prediction = self.predictor.predict(test_data, model_name='ensemble')
            
            if prediction and 'probabilities' in prediction:
                probability = prediction['probabilities'][0]
                prediction_score = probability * 100  # Convert to 0-100 scale
                
                # Calculate confidence based on model agreement
                if 'individual_probabilities' in prediction:
                    individual_probs = list(prediction['individual_probabilities'].values())
                    if len(individual_probs) > 1:
                        prob_std = np.std(individual_probs)
                        confidence = max(0, 1 - prob_std * 2)  # Higher std = lower confidence
                    else:
                        confidence = 0.7  # Default confidence for single model
                else:
                    confidence = 0.7
                
                return prediction_score, confidence
            
        except Exception as e:
            logger.warning(f"Error getting ML prediction for {symbol}: {str(e)}")
        
        return 50.0, 0.0  # Neutral prediction with no confidence
    
    def get_sentiment_score(self, symbol: str) -> float:
        """
        Get sentiment score for a stock.
        
        Args:
            symbol: Stock symbol
        
        Returns:
            Sentiment score (0-100)
        """
        try:
            sentiment_data = self.sentiment_analyzer.get_comprehensive_sentiment_score(
                symbol, self.data_collector
            )
            
            if sentiment_data:
                # Convert -1 to 1 scale to 0-100 scale
                composite_score = sentiment_data.get('composite_score', 0)
                sentiment_score = (composite_score + 1) * 50  # Convert to 0-100
                
                # Weight by confidence
                confidence = sentiment_data.get('confidence', 0.5)
                return sentiment_score * confidence + 50 * (1 - confidence)
            
        except Exception as e:
            logger.warning(f"Error getting sentiment for {symbol}: {str(e)}")
        
        return 50.0  # Neutral sentiment
    
    def apply_filters(self, symbol: str, data: pd.DataFrame, company_info: Dict = None) -> bool:
        """
        Apply filtering criteria to stock.
        
        Args:
            symbol: Stock symbol
            data: Stock data
            company_info: Company information
        
        Returns:
            True if stock passes filters
        """
        if data.empty:
            return False
        
        latest = data.iloc[-1]
        
        try:
            # Price filters
            current_price = latest['Close']
            min_price = self.filters.get('min_price', 5.0)
            max_price = self.filters.get('max_price', 1000.0)
            
            if current_price < min_price or current_price > max_price:
                logger.debug(f"{symbol} filtered out: price ${current_price:.2f}")
                return False
            
            # Volume filter
            if 'Volume' in latest:
                avg_volume = data['Volume'].tail(20).mean()
                min_volume = self.filters.get('min_volume', 1000000)
                
                if avg_volume < min_volume:
                    logger.debug(f"{symbol} filtered out: low volume {avg_volume:,.0f}")
                    return False
            
            # Exclude penny stocks
            if self.filters.get('exclude_penny_stocks', True) and current_price < 5.0:
                logger.debug(f"{symbol} filtered out: penny stock")
                return False
            
            # Market cap filter (if company info available)
            if company_info and 'market_cap' in company_info:
                market_cap = company_info['market_cap']
                if market_cap and market_cap < 1e9:  # $1B minimum
                    logger.debug(f"{symbol} filtered out: small market cap")
                    return False
            
        except Exception as e:
            logger.warning(f"Error applying filters to {symbol}: {str(e)}")
            return False
        
        return True
    
    def rank_stocks(self, symbols: List[str]) -> pd.DataFrame:
        """
        Rank all stocks and return top candidates.
        
        Args:
            symbols: List of stock symbols to analyze
        
        Returns:
            DataFrame with ranked stocks
        """
        logger.info(f"Starting stock ranking for {len(symbols)} symbols...")
        
        # Fetch and prepare data
        prepared_data = self.fetch_and_prepare_data(symbols)
        
        ranking_results = []
        
        for symbol, data in prepared_data.items():
            try:
                logger.info(f"Analyzing {symbol}...")
                
                # Get company info
                company_info = self.data_collector.fetch_company_info(symbol)
                
                # Apply filters
                if not self.apply_filters(symbol, data, company_info):
                    continue
                
                # Calculate individual scores
                technical_score = self.calculate_technical_score(data)
                momentum_score = self.calculate_momentum_score(data)
                volume_score = self.calculate_volume_score(data)
                sentiment_score = self.get_sentiment_score(symbol)
                
                # Get ML prediction
                ml_score, ml_confidence = self.get_ml_prediction_score(symbol, data)
                
                # Calculate weighted composite score
                composite_score = (
                    technical_score * self.weights.get('technical_score', 0.30) +
                    ml_score * self.weights.get('ml_prediction', 0.25) +
                    momentum_score * self.weights.get('momentum_score', 0.20) +
                    volume_score * self.weights.get('volume_score', 0.15) +
                    sentiment_score * self.weights.get('sentiment_score', 0.10)
                )
                
                # Get current price and basic info
                current_price = data['Close'].iloc[-1]
                daily_change = data['Daily_Return'].iloc[-1] * 100
                volume = data['Volume'].iloc[-1]
                
                # Get recent technical indicators
                latest = data.iloc[-1]
                rsi = latest.get('RSI', np.nan)
                macd = latest.get('MACD', np.nan)
                
                ranking_results.append({
                    'Symbol': symbol,
                    'Company_Name': company_info.get('name', 'N/A') if company_info else 'N/A',
                    'Sector': company_info.get('sector', 'N/A') if company_info else 'N/A',
                    'Current_Price': current_price,
                    'Daily_Change_Pct': daily_change,
                    'Volume': volume,
                    'Composite_Score': composite_score,
                    'Technical_Score': technical_score,
                    'ML_Score': ml_score,
                    'ML_Confidence': ml_confidence,
                    'Momentum_Score': momentum_score,
                    'Volume_Score': volume_score,
                    'Sentiment_Score': sentiment_score,
                    'RSI': rsi,
                    'MACD': macd,
                    'Analysis_Date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {str(e)}")
                continue
        
        if not ranking_results:
            logger.warning("No stocks passed analysis")
            return pd.DataFrame()
        
        # Create DataFrame and sort by composite score
        results_df = pd.DataFrame(ranking_results)
        results_df = results_df.sort_values('Composite_Score', ascending=False)
        
        logger.info(f"Successfully analyzed {len(results_df)} stocks")
        return results_df
    
    def get_top_10_recommendations(self, symbols: List[str] = None) -> Dict[str, Any]:
        """
        Get top 10 stock recommendations.
        
        Args:
            symbols: List of symbols to analyze (uses config default if None)
        
        Returns:
            Dictionary with top 10 recommendations and analysis summary
        """
        if symbols is None:
            symbols = self.config.get('stock_config', {}).get('symbols', [])
        
        if not symbols:
            raise ValueError("No symbols provided for analysis")
        
        logger.info("Generating top 10 stock recommendations...")
        
        # Rank all stocks
        rankings = self.rank_stocks(symbols)
        
        if rankings.empty:
            return {
                'top_10': pd.DataFrame(),
                'analysis_summary': {
                    'total_analyzed': 0,
                    'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'market_sentiment': 'Unknown'
                }
            }
        
        # Get top 10
        top_10 = rankings.head(self.ranking_config.get('top_picks', 10))
        
        # Generate analysis summary
        analysis_summary = {
            'total_analyzed': len(rankings),
            'total_symbols_attempted': len(symbols),
            'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'average_composite_score': rankings['Composite_Score'].mean(),
            'top_score': rankings['Composite_Score'].max() if len(rankings) > 0 else 0,
            'market_sentiment': self._get_market_sentiment_summary(),
            'sector_distribution': top_10['Sector'].value_counts().to_dict(),
            'confidence_stats': {
                'avg_ml_confidence': top_10['ML_Confidence'].mean(),
                'high_confidence_picks': len(top_10[top_10['ML_Confidence'] > 0.7])
            }
        }
        
        logger.info(f"Top 10 recommendations generated. Best score: {analysis_summary['top_score']:.1f}")
        
        return {
            'top_10': top_10,
            'analysis_summary': analysis_summary,
            'full_rankings': rankings
        }
    
    def _get_market_sentiment_summary(self) -> str:
        """Get overall market sentiment summary."""
        try:
            # Get market data
            market_data = self.data_collector.fetch_market_data()
            
            if market_data:
                spy_change = market_data.get('SPY', {}).get('change_pct', 0)
                
                if spy_change > 1:
                    return "Bullish"
                elif spy_change > 0:
                    return "Positive"
                elif spy_change > -1:
                    return "Negative"
                else:
                    return "Bearish"
            
        except Exception as e:
            logger.warning(f"Error getting market sentiment: {str(e)}")
        
        return "Neutral"
    
    def save_recommendations(self, recommendations: Dict[str, Any], filename: str = None) -> str:
        """
        Save recommendations to CSV file.
        
        Args:
            recommendations: Recommendations dictionary
            filename: Output filename (auto-generated if None)
        
        Returns:
            Path to saved file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"data/stock_recommendations_{timestamp}.csv"
        
        try:
            top_10 = recommendations['top_10']
            if not top_10.empty:
                top_10.to_csv(filename, index=False)
                logger.info(f"Recommendations saved to {filename}")
            
            return filename
            
        except Exception as e:
            logger.error(f"Error saving recommendations: {str(e)}")
            return ""


if __name__ == "__main__":
    # Example usage
    ranker = StockRanker()
    
    # Test with a smaller subset
    test_symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM', 'V', 'UNH']
    
    print("Generating stock recommendations...")
    recommendations = ranker.get_top_10_recommendations(test_symbols)
    
    if not recommendations['top_10'].empty:
        print("\nTOP 10 STOCK RECOMMENDATIONS:")
        print("=" * 80)
        
        top_10 = recommendations['top_10']
        for idx, row in top_10.iterrows():
            print(f"{row['Symbol']:6} | {row['Company_Name'][:30]:30} | "
                  f"Score: {row['Composite_Score']:5.1f} | "
                  f"Price: ${row['Current_Price']:7.2f} | "
                  f"Change: {row['Daily_Change_Pct']:5.1f}%")
        
        print("\nANALYSIS SUMMARY:")
        summary = recommendations['analysis_summary']
        print(f"Total analyzed: {summary['total_analyzed']}")
        print(f"Average score: {summary['average_composite_score']:.1f}")
        print(f"Market sentiment: {summary['market_sentiment']}")
        
        # Save results
        filename = ranker.save_recommendations(recommendations)
        if filename:
            print(f"\nResults saved to: {filename}")
    
    else:
        print("No recommendations generated. Check logs for errors.")