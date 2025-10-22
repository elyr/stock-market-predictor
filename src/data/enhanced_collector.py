"""
Enhanced Data Collector with Real-Time Capabilities
Integrates real-time data for more precise analysis
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

# Import our modules
from .realtime_provider import RealTimeDataProvider
from .collector import DataCollector as BaseDataCollector

logger = logging.getLogger(__name__)


class EnhancedDataCollector(BaseDataCollector):
    """
    Enhanced data collector with real-time capabilities for precise analysis.
    """
    
    def __init__(self, alpha_vantage_key=None, polygon_key=None, finnhub_key=None):
        """
        Initialize enhanced collector with real-time providers.
        
        Args:
            alpha_vantage_key: Alpha Vantage API key
            polygon_key: Polygon.io API key
            finnhub_key: Finnhub API key
        """
        super().__init__(alpha_vantage_key)
        
        # Initialize real-time provider
        self.realtime_provider = RealTimeDataProvider(
            alpha_vantage_key=alpha_vantage_key,
            polygon_key=polygon_key,
            finnhub_key=finnhub_key
        )
        
        # Real-time data cache
        self.realtime_cache = {}
        self.cache_expiry_seconds = 30  # 30-second cache for real-time data
        
        logger.info("Enhanced data collector initialized with real-time capabilities")
    
    def get_real_time_price(self, symbol: str) -> Dict:
        """
        Get current real-time price with enhanced accuracy.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with real-time price data
        """
        try:
            # Check cache first
            cache_key = f"realtime_{symbol}"
            if cache_key in self.realtime_cache:
                cached_data, timestamp = self.realtime_cache[cache_key]
                if (datetime.now() - timestamp).seconds < self.cache_expiry_seconds:
                    return cached_data
            
            # Get fresh real-time data
            quote_data = self.realtime_provider.get_real_time_quote(symbol)
            
            if quote_data:
                # Cache the result
                self.realtime_cache[cache_key] = (quote_data, datetime.now())
                
                logger.info(f"Real-time price for {symbol}: ${quote_data.get('price', 'N/A')}")
                return quote_data
            else:
                # Fallback to base collector
                logger.warning(f"Real-time data unavailable for {symbol}, using fallback")
                return self._get_fallback_price(symbol)
                
        except Exception as e:
            logger.error(f"Error getting real-time price for {symbol}: {str(e)}")
            return self._get_fallback_price(symbol)
    
    def _get_fallback_price(self, symbol: str) -> Dict:
        """Fallback to historical data when real-time fails."""
        try:
            data = self.fetch_stock_data(symbol, period='1d')
            if data is not None and not data.empty:
                latest = data.iloc[-1]
                return {
                    'symbol': symbol,
                    'price': float(latest['Close']),
                    'open': float(latest['Open']),
                    'high': float(latest['High']),
                    'low': float(latest['Low']),
                    'volume': int(latest['Volume']),
                    'timestamp': datetime.now(),
                    'change': float(latest['Close'] - latest['Open']),
                    'change_percent': ((latest['Close'] - latest['Open']) / latest['Open']) * 100,
                    'provider': 'fallback_historical'
                }
            return {}
        except Exception as e:
            logger.error(f"Fallback failed for {symbol}: {str(e)}")
            return {}
    
    def get_enhanced_stock_data(self, symbol: str, period: str = '6mo', 
                               include_realtime: bool = True) -> pd.DataFrame:
        """
        Get enhanced stock data combining historical and real-time data.
        
        Args:
            symbol: Stock symbol
            period: Historical data period
            include_realtime: Whether to include real-time data point
            
        Returns:
            Enhanced DataFrame with historical + real-time data
        """
        try:
            # Get historical data
            historical_data = self.fetch_stock_data(symbol, period=period)
            
            if historical_data is None or historical_data.empty:
                logger.warning(f"No historical data for {symbol}")
                return pd.DataFrame()
            
            # Add real-time data point if requested and market is open
            if include_realtime:
                market_status = self.realtime_provider.get_market_status()
                
                if market_status.get('is_open', False):
                    realtime_quote = self.get_real_time_price(symbol)
                    
                    if realtime_quote and realtime_quote.get('price'):
                        # Create real-time data point
                        rt_timestamp = datetime.now().replace(second=0, microsecond=0)
                        
                        # Avoid duplicate timestamps
                        if rt_timestamp not in historical_data.index:
                            rt_data = pd.DataFrame({
                                'Open': [realtime_quote.get('price')],
                                'High': [realtime_quote.get('price')],
                                'Low': [realtime_quote.get('price')],
                                'Close': [realtime_quote.get('price')],
                                'Volume': [realtime_quote.get('volume', 0)],
                                'Adj Close': [realtime_quote.get('price')]
                            }, index=[rt_timestamp])
                            
                            # Append real-time data
                            historical_data = pd.concat([historical_data, rt_data])
                            historical_data = historical_data.sort_index()
                            
                            logger.info(f"Added real-time data point for {symbol}")
            
            return historical_data
            
        except Exception as e:
            logger.error(f"Error getting enhanced data for {symbol}: {str(e)}")
            return self.fetch_stock_data(symbol, period=period) or pd.DataFrame()
    
    def get_real_time_portfolio_data(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Get real-time data for entire portfolio efficiently.
        
        Args:
            symbols: List of stock symbols
            
        Returns:
            Dictionary mapping symbols to their real-time data
        """
        logger.info(f"Fetching real-time portfolio data for {len(symbols)} symbols")
        
        try:
            # Use concurrent fetching for efficiency
            portfolio_data = self.realtime_provider.get_multiple_quotes(symbols)
            
            # Add market context
            market_status = self.realtime_provider.get_market_status()
            
            # Enhance with additional metrics
            for symbol, data in portfolio_data.items():
                if data:
                    # Add volume analysis
                    if data.get('volume') and data.get('volume_avg'):
                        data['volume_ratio'] = data['volume'] / data['volume_avg']
                    
                    # Add momentum indicators
                    data['is_gaining'] = data.get('change_percent', 0) > 0
                    data['momentum_strength'] = abs(data.get('change_percent', 0))
                    
                    # Market context
                    data['market_open'] = market_status.get('is_open', False)
            
            logger.info(f"Successfully fetched real-time data for {len(portfolio_data)} symbols")
            return portfolio_data
            
        except Exception as e:
            logger.error(f"Error getting portfolio real-time data: {str(e)}")
            return {}
    
    def get_precision_analysis_data(self, symbols: List[str]) -> Dict:
        """
        Get high-precision data for analysis combining multiple sources.
        
        Args:
            symbols: List of stock symbols
            
        Returns:
            Dictionary with comprehensive precision data
        """
        logger.info(f"Gathering precision analysis data for {len(symbols)} symbols")
        
        analysis_data = {
            'timestamp': datetime.now(),
            'symbols_analyzed': symbols,
            'real_time_quotes': {},
            'intraday_data': {},
            'extended_hours_data': {},
            'market_context': {},
            'data_quality': {}
        }
        
        try:
            # Get market status and context
            market_status = self.realtime_provider.get_market_status()
            analysis_data['market_context'] = market_status
            
            # Get real-time quotes for all symbols
            real_time_quotes = self.get_real_time_portfolio_data(symbols)
            analysis_data['real_time_quotes'] = real_time_quotes
            
            # Get intraday data for key symbols (limit to avoid rate limits)
            key_symbols = symbols[:5]  # Limit to top 5 for detailed analysis
            
            for symbol in key_symbols:
                try:
                    # Intraday data
                    intraday = self.realtime_provider.get_intraday_data(symbol, interval='5m')
                    if not intraday.empty:
                        analysis_data['intraday_data'][symbol] = {
                            'latest_price': float(intraday['Close'].iloc[-1]),
                            'price_trend': intraday['Close'].pct_change().iloc[-5:].mean() * 100,
                            'volume_trend': intraday['Volume'].pct_change().iloc[-5:].mean() * 100,
                            'volatility': intraday['Close'].pct_change().std() * 100,
                            'data_points': len(intraday)
                        }
                    
                    # Extended hours data
                    extended = self.realtime_provider.get_extended_market_data(symbol)
                    if extended:
                        analysis_data['extended_hours_data'][symbol] = extended
                        
                except Exception as e:
                    logger.warning(f"Error getting detailed data for {symbol}: {str(e)}")
                    continue
            
            # Calculate data quality metrics
            total_symbols = len(symbols)
            successful_quotes = len([q for q in real_time_quotes.values() if q])
            
            analysis_data['data_quality'] = {
                'quote_success_rate': (successful_quotes / total_symbols) * 100 if total_symbols > 0 else 0,
                'intraday_coverage': len(analysis_data['intraday_data']),
                'extended_hours_coverage': len(analysis_data['extended_hours_data']),
                'overall_quality_score': (successful_quotes / total_symbols) * 100 if total_symbols > 0 else 0
            }
            
            logger.info(f"Precision analysis completed: {successful_quotes}/{total_symbols} quotes successful")
            return analysis_data
            
        except Exception as e:
            logger.error(f"Error in precision analysis: {str(e)}")
            analysis_data['error'] = str(e)
            return analysis_data
    
    def get_real_time_market_indicators(self) -> Dict:
        """
        Get real-time market indicators for context.
        
        Returns:
            Dictionary with market indicators
        """
        try:
            # Key market indicators
            market_symbols = {
                'SPY': 'S&P 500',
                'QQQ': 'NASDAQ-100',
                'DIA': 'Dow Jones',
                'IWM': 'Russell 2000',
                'VIX': 'Volatility Index',
                'TLT': 'Treasury Bonds',
                'GLD': 'Gold',
                'DXY': 'US Dollar Index'
            }
            
            logger.info("Fetching real-time market indicators")
            
            # Get real-time data for market indicators
            market_data = self.realtime_provider.get_multiple_quotes(list(market_symbols.keys()))
            
            # Process and enhance market data
            indicators = {}
            for symbol, name in market_symbols.items():
                if symbol in market_data and market_data[symbol]:
                    data = market_data[symbol]
                    indicators[symbol] = {
                        'name': name,
                        'price': data.get('price', 0),
                        'change_percent': data.get('change_percent', 0),
                        'trend': 'UP' if data.get('change_percent', 0) > 0 else 'DOWN' if data.get('change_percent', 0) < 0 else 'FLAT',
                        'strength': abs(data.get('change_percent', 0))
                    }
            
            # Calculate market sentiment
            if indicators:
                positive_indicators = len([ind for ind in indicators.values() if ind['change_percent'] > 0])
                total_indicators = len(indicators)
                market_sentiment = (positive_indicators / total_indicators) * 100
                
                indicators['_summary'] = {
                    'market_sentiment_score': market_sentiment,
                    'positive_indicators': positive_indicators,
                    'total_indicators': total_indicators,
                    'sentiment_label': 'BULLISH' if market_sentiment > 60 else 'BEARISH' if market_sentiment < 40 else 'NEUTRAL'
                }
            
            logger.info(f"Market indicators fetched: {len(indicators)} successful")
            return indicators
            
        except Exception as e:
            logger.error(f"Error getting market indicators: {str(e)}")
            return {}
    
    def start_real_time_monitoring(self, symbols: List[str], update_callback=None):
        """
        Start real-time monitoring for given symbols.
        
        Args:
            symbols: Symbols to monitor
            update_callback: Function to call with updates
        """
        def monitoring_callback(data):
            if update_callback:
                enhanced_data = {
                    'timestamp': datetime.now(),
                    'quotes': data,
                    'market_indicators': self.get_real_time_market_indicators()
                }
                update_callback(enhanced_data)
        
        # Start streaming
        stream_thread = self.realtime_provider.start_real_time_stream(symbols, monitoring_callback)
        
        logger.info(f"Started real-time monitoring for {len(symbols)} symbols")
        return stream_thread


def test_enhanced_collector():
    """Test the enhanced data collector."""
    print("🚀 Testing Enhanced Data Collector")
    print("=" * 50)
    
    collector = EnhancedDataCollector()
    
    test_symbols = ['AAPL', 'MSFT', 'GOOGL']
    
    print("1. Testing real-time price fetching...")
    for symbol in test_symbols:
        price_data = collector.get_real_time_price(symbol)
        if price_data:
            print(f"   {symbol}: ${price_data.get('price', 'N/A')} ({price_data.get('change_percent', 0):+.2f}%)")
        else:
            print(f"   {symbol}: ❌ No data")
    
    print("\n2. Testing enhanced stock data...")
    enhanced_data = collector.get_enhanced_stock_data('AAPL', period='5d', include_realtime=True)
    print(f"   AAPL enhanced data: {len(enhanced_data)} data points")
    if not enhanced_data.empty:
        print(f"   Latest price: ${enhanced_data['Close'].iloc[-1]:.2f}")
    
    print("\n3. Testing precision analysis...")
    precision_data = collector.get_precision_analysis_data(test_symbols[:2])  # Limit for testing
    quality = precision_data.get('data_quality', {})
    print(f"   Quote success rate: {quality.get('quote_success_rate', 0):.1f}%")
    print(f"   Overall quality score: {quality.get('overall_quality_score', 0):.1f}%")
    
    print("\n4. Testing market indicators...")
    indicators = collector.get_real_time_market_indicators()
    if '_summary' in indicators:
        summary = indicators['_summary']
        print(f"   Market sentiment: {summary.get('sentiment_label', 'UNKNOWN')}")
        print(f"   Sentiment score: {summary.get('market_sentiment_score', 0):.1f}%")
    
    print("\n✅ Enhanced data collector test completed!")


if __name__ == "__main__":
    test_enhanced_collector()