"""
Market sentiment analysis module using news, social media, and market data.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import logging
import requests
from datetime import datetime, timedelta
import re
from textblob import TextBlob
import yfinance as yf

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """
    Analyzes market sentiment from various sources including news and market indicators.
    """
    
    def __init__(self):
        self.fear_greed_cache = {}
        self.news_cache = {}
    
    def analyze_news_sentiment(self, news_articles: List[Dict]) -> Dict[str, float]:
        """
        Analyze sentiment from news articles.
        
        Args:
            news_articles: List of news articles with title and summary
        
        Returns:
            Dictionary with sentiment scores
        """
        if not news_articles:
            return {'sentiment_score': 0.0, 'sentiment_label': 'neutral', 'confidence': 0.0}
        
        sentiments = []
        
        for article in news_articles:
            # Combine title and summary for analysis
            text = f"{article.get('title', '')} {article.get('summary', '')}"
            
            if text.strip():
                # Use TextBlob for sentiment analysis
                blob = TextBlob(text)
                sentiment = blob.sentiment.polarity  # -1 to 1
                sentiments.append(sentiment)
        
        if not sentiments:
            return {'sentiment_score': 0.0, 'sentiment_label': 'neutral', 'confidence': 0.0}
        
        # Calculate aggregate sentiment
        avg_sentiment = np.mean(sentiments)
        sentiment_std = np.std(sentiments)
        confidence = 1 - min(sentiment_std, 1.0)  # Lower std = higher confidence
        
        # Classify sentiment
        if avg_sentiment > 0.1:
            sentiment_label = 'positive'
        elif avg_sentiment < -0.1:
            sentiment_label = 'negative'
        else:
            sentiment_label = 'neutral'
        
        return {
            'sentiment_score': avg_sentiment,
            'sentiment_label': sentiment_label,
            'confidence': confidence,
            'num_articles': len(sentiments)
        }
    
    def get_market_fear_greed_index(self) -> Optional[Dict]:
        """
        Get Fear & Greed Index (CNN Business).
        Note: This is a simplified version. In practice, you'd need to scrape or use an API.
        
        Returns:
            Dictionary with fear/greed metrics
        """
        # Check cache first
        cache_key = datetime.now().strftime("%Y-%m-%d")
        if cache_key in self.fear_greed_cache:
            return self.fear_greed_cache[cache_key]
        
        try:
            # For demonstration, we'll calculate a simple fear/greed proxy using VIX
            vix_ticker = yf.Ticker("^VIX")
            vix_data = vix_ticker.history(period="5d")
            
            if not vix_data.empty:
                current_vix = vix_data['Close'].iloc[-1]
                
                # Convert VIX to fear/greed scale (0-100, where 0 is extreme fear, 100 is extreme greed)
                # VIX typically ranges from 10-80, with 20 being normal
                if current_vix <= 15:
                    fear_greed_score = 80  # Low VIX = Greed
                elif current_vix <= 20:
                    fear_greed_score = 60  # Normal
                elif current_vix <= 30:
                    fear_greed_score = 40  # Some fear
                elif current_vix <= 40:
                    fear_greed_score = 20  # Fear
                else:
                    fear_greed_score = 10  # Extreme fear
                
                result = {
                    'fear_greed_index': fear_greed_score,
                    'vix_level': current_vix,
                    'interpretation': self._interpret_fear_greed(fear_greed_score),
                    'date': datetime.now().date()
                }
                
                # Cache the result
                self.fear_greed_cache[cache_key] = result
                return result
        
        except Exception as e:
            logger.error(f"Error fetching fear/greed index: {str(e)}")
        
        return None
    
    def _interpret_fear_greed(self, score: float) -> str:
        """Interpret fear/greed score."""
        if score >= 75:
            return "Extreme Greed"
        elif score >= 55:
            return "Greed"
        elif score >= 45:
            return "Neutral"
        elif score >= 25:
            return "Fear"
        else:
            return "Extreme Fear"
    
    def analyze_market_breadth(self, symbols: List[str], data_collector) -> Dict[str, float]:
        """
        Analyze market breadth indicators.
        
        Args:
            symbols: List of stock symbols to analyze
            data_collector: DataCollector instance
        
        Returns:
            Dictionary with breadth indicators
        """
        advancing_stocks = 0
        declining_stocks = 0
        unchanged_stocks = 0
        total_volume_up = 0
        total_volume_down = 0
        
        valid_stocks = 0
        
        for symbol in symbols[:50]:  # Limit to avoid rate limits
            try:
                data = data_collector.fetch_stock_data(symbol, period="2d")
                
                if data is not None and len(data) >= 2:
                    current_close = data['Close'].iloc[-1]
                    previous_close = data['Close'].iloc[-2]
                    current_volume = data['Volume'].iloc[-1]
                    
                    change = current_close - previous_close
                    
                    if change > 0:
                        advancing_stocks += 1
                        total_volume_up += current_volume
                    elif change < 0:
                        declining_stocks += 1
                        total_volume_down += current_volume
                    else:
                        unchanged_stocks += 1
                    
                    valid_stocks += 1
            
            except Exception as e:
                logger.warning(f"Error processing {symbol} for breadth analysis: {str(e)}")
        
        if valid_stocks == 0:
            return {}
        
        # Calculate breadth indicators
        advance_decline_ratio = advancing_stocks / declining_stocks if declining_stocks > 0 else float('inf')
        advance_decline_line = advancing_stocks - declining_stocks
        breadth_percentage = (advancing_stocks / valid_stocks) * 100
        
        # Up/Down Volume Ratio
        updown_volume_ratio = total_volume_up / total_volume_down if total_volume_down > 0 else float('inf')
        
        return {
            'advancing_stocks': advancing_stocks,
            'declining_stocks': declining_stocks,
            'unchanged_stocks': unchanged_stocks,
            'advance_decline_ratio': advance_decline_ratio,
            'advance_decline_line': advance_decline_line,
            'breadth_percentage': breadth_percentage,
            'updown_volume_ratio': updown_volume_ratio,
            'total_stocks_analyzed': valid_stocks
        }
    
    def analyze_sector_sentiment(self, data_collector) -> Dict[str, Dict]:
        """
        Analyze sentiment by sector using sector ETFs.
        
        Args:
            data_collector: DataCollector instance
        
        Returns:
            Dictionary with sector sentiment data
        """
        sector_etfs = {
            'Technology': 'XLK',
            'Healthcare': 'XLV',
            'Financials': 'XLF',
            'Consumer Discretionary': 'XLY',
            'Communication Services': 'XLC',
            'Industrials': 'XLI',
            'Consumer Staples': 'XLP',
            'Energy': 'XLE',
            'Utilities': 'XLU',
            'Real Estate': 'XLRE',
            'Materials': 'XLB'
        }
        
        sector_sentiment = {}
        
        for sector, etf in sector_etfs.items():
            try:
                data = data_collector.fetch_stock_data(etf, period="1mo")
                
                if data is not None and len(data) >= 20:
                    # Calculate various sentiment indicators
                    current_price = data['Close'].iloc[-1]
                    sma_20 = data['Close'].rolling(20).mean().iloc[-1]
                    
                    # Price momentum
                    returns_5d = (data['Close'].iloc[-1] / data['Close'].iloc[-6] - 1) * 100
                    returns_20d = (data['Close'].iloc[-1] / data['Close'].iloc[-21] - 1) * 100
                    
                    # Volatility
                    volatility = data['Close'].pct_change().std() * np.sqrt(252) * 100
                    
                    # Relative strength
                    price_vs_sma = ((current_price / sma_20) - 1) * 100
                    
                    # Volume analysis
                    avg_volume = data['Volume'].rolling(20).mean().iloc[-1]
                    recent_volume = data['Volume'].iloc[-1]
                    volume_ratio = recent_volume / avg_volume
                    
                    # Overall sentiment score (0-100)
                    sentiment_components = [
                        min(max((returns_5d + 5) * 10, 0), 100),  # 5-day returns
                        min(max((returns_20d + 10) * 5, 0), 100),  # 20-day returns
                        min(max((price_vs_sma + 5) * 10, 0), 100),  # Price vs SMA
                        min(max(100 - volatility * 2, 0), 100),  # Low volatility is good
                        min(max(volume_ratio * 25, 0), 100)  # Volume confirmation
                    ]
                    
                    sentiment_score = np.mean(sentiment_components)
                    
                    sector_sentiment[sector] = {
                        'sentiment_score': sentiment_score,
                        'returns_5d': returns_5d,
                        'returns_20d': returns_20d,
                        'volatility': volatility,
                        'price_vs_sma': price_vs_sma,
                        'volume_ratio': volume_ratio,
                        'etf_symbol': etf
                    }
            
            except Exception as e:
                logger.warning(f"Error analyzing sector {sector}: {str(e)}")
        
        return sector_sentiment
    
    def calculate_put_call_ratio(self, data_collector) -> Optional[Dict]:
        """
        Calculate Put/Call ratio as a sentiment indicator.
        Note: This requires options data which is limited in free APIs.
        
        Args:
            data_collector: DataCollector instance
        
        Returns:
            Dictionary with put/call ratio data
        """
        try:
            # For demonstration, we'll use VIX as a proxy for options sentiment
            vix_data = data_collector.fetch_stock_data("^VIX", period="1mo")
            
            if vix_data is not None and len(vix_data) >= 20:
                current_vix = vix_data['Close'].iloc[-1]
                avg_vix = vix_data['Close'].rolling(20).mean().iloc[-1]
                
                # Convert VIX levels to put/call sentiment
                vix_ratio = current_vix / avg_vix
                
                # Interpret the ratio
                if vix_ratio > 1.3:
                    sentiment = "Bearish"
                elif vix_ratio > 1.1:
                    sentiment = "Cautious"
                elif vix_ratio < 0.8:
                    sentiment = "Bullish"
                else:
                    sentiment = "Neutral"
                
                return {
                    'vix_ratio': vix_ratio,
                    'current_vix': current_vix,
                    'average_vix': avg_vix,
                    'sentiment': sentiment
                }
        
        except Exception as e:
            logger.error(f"Error calculating put/call ratio: {str(e)}")
        
        return None
    
    def get_comprehensive_sentiment_score(self, symbol: str, data_collector) -> Dict[str, float]:
        """
        Calculate a comprehensive sentiment score combining multiple factors.
        
        Args:
            symbol: Stock symbol
            data_collector: DataCollector instance
        
        Returns:
            Dictionary with comprehensive sentiment analysis
        """
        sentiment_factors = {}
        
        try:
            # Get company news
            news = data_collector.get_stock_news(symbol, num_articles=10)
            news_sentiment = self.analyze_news_sentiment(news)
            sentiment_factors['news_sentiment'] = news_sentiment['sentiment_score']
            
            # Get market-wide sentiment
            fear_greed = self.get_market_fear_greed_index()
            if fear_greed:
                # Convert 0-100 scale to -1 to 1 scale
                sentiment_factors['market_sentiment'] = (fear_greed['fear_greed_index'] - 50) / 50
            
            # Get sector sentiment
            company_info = data_collector.fetch_company_info(symbol)
            if company_info and company_info.get('sector'):
                sector_sentiment = self.analyze_sector_sentiment(data_collector)
                sector = company_info['sector']
                if sector in sector_sentiment:
                    # Convert 0-100 scale to -1 to 1 scale
                    sentiment_factors['sector_sentiment'] = (sector_sentiment[sector]['sentiment_score'] - 50) / 50
            
            # Get options sentiment
            options_sentiment = self.calculate_put_call_ratio(data_collector)
            if options_sentiment:
                # Convert VIX ratio to sentiment (-1 to 1)
                vix_sentiment = 1 - min(max(options_sentiment['vix_ratio'] - 0.5, 0), 1)
                sentiment_factors['options_sentiment'] = (vix_sentiment - 0.5) * 2
            
            # Calculate weighted composite score
            weights = {
                'news_sentiment': 0.4,
                'market_sentiment': 0.3,
                'sector_sentiment': 0.2,
                'options_sentiment': 0.1
            }
            
            composite_score = 0
            total_weight = 0
            
            for factor, score in sentiment_factors.items():
                if factor in weights and score is not None:
                    composite_score += weights[factor] * score
                    total_weight += weights[factor]
            
            if total_weight > 0:
                composite_score /= total_weight
            
            # Classify overall sentiment
            if composite_score > 0.2:
                overall_sentiment = "Bullish"
            elif composite_score > 0.05:
                overall_sentiment = "Slightly Bullish"
            elif composite_score < -0.2:
                overall_sentiment = "Bearish"
            elif composite_score < -0.05:
                overall_sentiment = "Slightly Bearish"
            else:
                overall_sentiment = "Neutral"
            
            return {
                'composite_score': composite_score,
                'overall_sentiment': overall_sentiment,
                'confidence': min(total_weight, 1.0),
                'factors': sentiment_factors
            }
        
        except Exception as e:
            logger.error(f"Error calculating comprehensive sentiment for {symbol}: {str(e)}")
            return {
                'composite_score': 0.0,
                'overall_sentiment': "Neutral",
                'confidence': 0.0,
                'factors': {}
            }


if __name__ == "__main__":
    # Example usage
    from ..data import DataCollector
    
    collector = DataCollector()
    analyzer = SentimentAnalyzer()
    
    # Test with a sample stock
    symbol = 'AAPL'
    
    print(f"Analyzing sentiment for {symbol}...")
    
    # Get comprehensive sentiment
    sentiment = analyzer.get_comprehensive_sentiment_score(symbol, collector)
    print(f"Composite sentiment score: {sentiment['composite_score']:.3f}")
    print(f"Overall sentiment: {sentiment['overall_sentiment']}")
    print(f"Confidence: {sentiment['confidence']:.2f}")
    
    # Get market breadth
    test_symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']
    breadth = analyzer.analyze_market_breadth(test_symbols, collector)
    if breadth:
        print(f"\nMarket Breadth:")
        print(f"Advancing: {breadth['advancing_stocks']}, Declining: {breadth['declining_stocks']}")
        print(f"Breadth percentage: {breadth['breadth_percentage']:.1f}%")
    
    # Get fear/greed index
    fear_greed = analyzer.get_market_fear_greed_index()
    if fear_greed:
        print(f"\nFear/Greed Index: {fear_greed['fear_greed_index']} ({fear_greed['interpretation']})")