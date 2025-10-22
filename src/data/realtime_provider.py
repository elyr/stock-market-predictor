"""
Real-time Data Provider Module
Enhanced data collection with multiple API sources for precise analysis
"""

import yfinance as yf
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import logging
from typing import Dict, List, Optional, Union
import json
import warnings
import websocket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)


class RealTimeDataProvider:
    """
    Enhanced real-time data provider with multiple API sources and WebSocket support.
    """
    
    def __init__(self, alpha_vantage_key=None, polygon_key=None, finnhub_key=None):
        """
        Initialize with API keys for various providers.
        
        Args:
            alpha_vantage_key: Alpha Vantage API key
            polygon_key: Polygon.io API key  
            finnhub_key: Finnhub API key
        """
        self.alpha_vantage_key = alpha_vantage_key
        self.polygon_key = polygon_key
        self.finnhub_key = finnhub_key
        
        # Rate limiting
        self.last_request_time = {}
        self.min_request_interval = 0.2  # 200ms between requests
        
        # Cache for real-time data
        self.real_time_cache = {}
        self.cache_expiry = 60  # Cache expires in 60 seconds
        
        # WebSocket connections
        self.ws_connections = {}
        self.streaming_data = {}
        
        logger.info("Real-time data provider initialized")
    
    def _rate_limit(self, provider: str):
        """Implement rate limiting for API calls."""
        current_time = time.time()
        if provider in self.last_request_time:
            time_since_last = current_time - self.last_request_time[provider]
            if time_since_last < self.min_request_interval:
                time.sleep(self.min_request_interval - time_since_last)
        
        self.last_request_time[provider] = time.time()
    
    def get_real_time_quote(self, symbol: str) -> Dict:
        """
        Get real-time quote with multiple fallback providers.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with real-time quote data
        """
        # Check cache first
        cache_key = f"{symbol}_quote"
        if cache_key in self.real_time_cache:
            cached_data, timestamp = self.real_time_cache[cache_key]
            if time.time() - timestamp < self.cache_expiry:
                return cached_data
        
        # Try multiple providers in order of preference
        providers = [
            self._get_yahoo_quote,
            self._get_alpha_vantage_quote,
            self._get_polygon_quote,
            self._get_finnhub_quote
        ]
        
        for provider in providers:
            try:
                quote_data = provider(symbol)
                if quote_data and quote_data.get('price'):
                    # Cache the result
                    self.real_time_cache[cache_key] = (quote_data, time.time())
                    return quote_data
            except Exception as e:
                logger.warning(f"Provider failed for {symbol}: {str(e)}")
                continue
        
        logger.error(f"All providers failed for {symbol}")
        return {}
    
    def _get_yahoo_quote(self, symbol: str) -> Dict:
        """Get real-time quote from Yahoo Finance."""
        try:
            self._rate_limit('yahoo')
            ticker = yf.Ticker(symbol)
            
            # Get real-time data
            info = ticker.info
            hist = ticker.history(period='1d', interval='1m')
            
            if hist.empty:
                return {}
            
            latest = hist.iloc[-1]
            
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
                'provider': 'yahoo',
                'bid': info.get('bid', latest['Close']),
                'ask': info.get('ask', latest['Close']),
                'market_cap': info.get('marketCap'),
                'pe_ratio': info.get('trailingPE'),
                'volume_avg': info.get('averageVolume')
            }
            
        except Exception as e:
            logger.error(f"Yahoo Finance error for {symbol}: {str(e)}")
            return {}
    
    def _get_alpha_vantage_quote(self, symbol: str) -> Dict:
        """Get real-time quote from Alpha Vantage."""
        if not self.alpha_vantage_key:
            return {}
        
        try:
            self._rate_limit('alpha_vantage')
            
            url = f"https://www.alphavantage.co/query"
            params = {
                'function': 'GLOBAL_QUOTE',
                'symbol': symbol,
                'apikey': self.alpha_vantage_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if 'Global Quote' not in data:
                return {}
            
            quote = data['Global Quote']
            
            return {
                'symbol': symbol,
                'price': float(quote.get('05. price', 0)),
                'open': float(quote.get('02. open', 0)),
                'high': float(quote.get('03. high', 0)),
                'low': float(quote.get('04. low', 0)),
                'volume': int(quote.get('06. volume', 0)),
                'timestamp': datetime.now(),
                'change': float(quote.get('09. change', 0)),
                'change_percent': float(quote.get('10. change percent', '0%').rstrip('%')),
                'provider': 'alpha_vantage',
                'previous_close': float(quote.get('08. previous close', 0))
            }
            
        except Exception as e:
            logger.error(f"Alpha Vantage error for {symbol}: {str(e)}")
            return {}
    
    def _get_polygon_quote(self, symbol: str) -> Dict:
        """Get real-time quote from Polygon.io."""
        if not self.polygon_key:
            return {}
        
        try:
            self._rate_limit('polygon')
            
            url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev"
            params = {
                'adjusted': 'true',
                'apikey': self.polygon_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get('status') != 'OK' or not data.get('results'):
                return {}
            
            result = data['results'][0]
            
            return {
                'symbol': symbol,
                'price': float(result.get('c', 0)),  # Close
                'open': float(result.get('o', 0)),   # Open
                'high': float(result.get('h', 0)),   # High
                'low': float(result.get('l', 0)),    # Low
                'volume': int(result.get('v', 0)),   # Volume
                'timestamp': datetime.now(),
                'change': float(result.get('c', 0) - result.get('o', 0)),
                'change_percent': ((result.get('c', 0) - result.get('o', 0)) / result.get('o', 1)) * 100,
                'provider': 'polygon',
                'vwap': float(result.get('vw', 0))   # Volume weighted average price
            }
            
        except Exception as e:
            logger.error(f"Polygon error for {symbol}: {str(e)}")
            return {}
    
    def _get_finnhub_quote(self, symbol: str) -> Dict:
        """Get real-time quote from Finnhub."""
        if not self.finnhub_key:
            return {}
        
        try:
            self._rate_limit('finnhub')
            
            url = f"https://finnhub.io/api/v1/quote"
            params = {
                'symbol': symbol,
                'token': self.finnhub_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if not data or data.get('c') == 0:
                return {}
            
            return {
                'symbol': symbol,
                'price': float(data.get('c', 0)),    # Current price
                'open': float(data.get('o', 0)),     # Open price
                'high': float(data.get('h', 0)),     # High price
                'low': float(data.get('l', 0)),      # Low price
                'timestamp': datetime.now(),
                'change': float(data.get('d', 0)),   # Change
                'change_percent': float(data.get('dp', 0)),  # Percent change
                'provider': 'finnhub',
                'previous_close': float(data.get('pc', 0))   # Previous close
            }
            
        except Exception as e:
            logger.error(f"Finnhub error for {symbol}: {str(e)}")
            return {}
    
    def get_multiple_quotes(self, symbols: List[str], max_workers: int = 10) -> Dict[str, Dict]:
        """
        Get real-time quotes for multiple symbols concurrently.
        
        Args:
            symbols: List of stock symbols
            max_workers: Maximum number of concurrent requests
            
        Returns:
            Dictionary mapping symbols to their quote data
        """
        results = {}
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all requests
            future_to_symbol = {
                executor.submit(self.get_real_time_quote, symbol): symbol 
                for symbol in symbols
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    quote_data = future.result(timeout=30)
                    if quote_data:
                        results[symbol] = quote_data
                        logger.info(f"Retrieved real-time data for {symbol}: ${quote_data.get('price', 'N/A')}")
                except Exception as e:
                    logger.error(f"Error getting quote for {symbol}: {str(e)}")
                    results[symbol] = {}
        
        return results
    
    def get_intraday_data(self, symbol: str, interval: str = '1m', period: str = '1d') -> pd.DataFrame:
        """
        Get high-frequency intraday data.
        
        Args:
            symbol: Stock symbol
            interval: Data interval (1m, 5m, 15m, 30m, 1h)
            period: Data period (1d, 5d, 1mo)
            
        Returns:
            DataFrame with intraday OHLCV data
        """
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period=period, interval=interval)
            
            if data.empty:
                logger.warning(f"No intraday data available for {symbol}")
                return pd.DataFrame()
            
            # Add real-time indicators
            data['timestamp'] = data.index
            data['symbol'] = symbol
            
            # Calculate some real-time metrics
            data['price_change'] = data['Close'].diff()
            data['price_change_pct'] = data['Close'].pct_change() * 100
            data['volume_sma'] = data['Volume'].rolling(window=20).mean()
            data['volume_ratio'] = data['Volume'] / data['volume_sma']
            
            logger.info(f"Retrieved {len(data)} intraday records for {symbol}")
            return data
            
        except Exception as e:
            logger.error(f"Error getting intraday data for {symbol}: {str(e)}")
            return pd.DataFrame()
    
    def get_market_status(self) -> Dict:
        """Get current market status and trading hours."""
        try:
            # Get market status from Yahoo Finance
            spy = yf.Ticker("SPY")
            hist = spy.history(period='1d', interval='1m')
            
            current_time = datetime.now()
            
            # Check if market is open (basic check)
            market_open_time = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close_time = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
            
            is_market_open = (
                current_time.weekday() < 5 and  # Monday to Friday
                market_open_time <= current_time <= market_close_time and
                not hist.empty
            )
            
            return {
                'is_open': is_market_open,
                'current_time': current_time,
                'market_open': market_open_time,
                'market_close': market_close_time,
                'timezone': 'EST',
                'last_data_time': hist.index[-1] if not hist.empty else None
            }
            
        except Exception as e:
            logger.error(f"Error getting market status: {str(e)}")
            return {'is_open': False, 'current_time': datetime.now()}
    
    def start_real_time_stream(self, symbols: List[str], callback_func=None):
        """
        Start real-time data streaming (simulated with periodic updates).
        
        Args:
            symbols: List of symbols to stream
            callback_func: Function to call with new data
        """
        def stream_worker():
            while True:
                try:
                    # Get fresh quotes for all symbols
                    quotes = self.get_multiple_quotes(symbols, max_workers=5)
                    
                    # Update streaming data
                    self.streaming_data.update(quotes)
                    
                    # Call callback if provided
                    if callback_func:
                        callback_func(quotes)
                    
                    # Wait before next update
                    time.sleep(30)  # Update every 30 seconds
                    
                except Exception as e:
                    logger.error(f"Streaming error: {str(e)}")
                    time.sleep(60)  # Wait longer on error
        
        # Start streaming in background thread
        stream_thread = threading.Thread(target=stream_worker, daemon=True)
        stream_thread.start()
        
        logger.info(f"Started real-time streaming for {len(symbols)} symbols")
        return stream_thread
    
    def get_extended_market_data(self, symbol: str) -> Dict:
        """
        Get extended market data including pre/post market.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with extended market data
        """
        try:
            ticker = yf.Ticker(symbol)
            
            # Get pre-market and after-hours data
            hist = ticker.history(period='1d', interval='1m', prepost=True)
            
            if hist.empty:
                return {}
            
            # Current market status
            market_status = self.get_market_status()
            
            # Regular market hours data
            regular_hours = hist.between_time('09:30', '16:00')
            pre_market = hist.between_time('04:00', '09:30')
            after_hours = hist.between_time('16:00', '20:00')
            
            latest = hist.iloc[-1]
            
            result = {
                'symbol': symbol,
                'current_price': float(latest['Close']),
                'timestamp': datetime.now(),
                'market_status': market_status,
                'regular_hours': {
                    'open': float(regular_hours.iloc[0]['Open']) if not regular_hours.empty else None,
                    'close': float(regular_hours.iloc[-1]['Close']) if not regular_hours.empty else None,
                    'high': float(regular_hours['High'].max()) if not regular_hours.empty else None,
                    'low': float(regular_hours['Low'].min()) if not regular_hours.empty else None,
                    'volume': int(regular_hours['Volume'].sum()) if not regular_hours.empty else None
                }
            }
            
            # Add pre-market data if available
            if not pre_market.empty:
                result['pre_market'] = {
                    'price': float(pre_market.iloc[-1]['Close']),
                    'change': float(pre_market.iloc[-1]['Close'] - pre_market.iloc[0]['Open']),
                    'volume': int(pre_market['Volume'].sum())
                }
            
            # Add after-hours data if available
            if not after_hours.empty:
                result['after_hours'] = {
                    'price': float(after_hours.iloc[-1]['Close']),
                    'change': float(after_hours.iloc[-1]['Close'] - after_hours.iloc[0]['Open']),
                    'volume': int(after_hours['Volume'].sum())
                }
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting extended market data for {symbol}: {str(e)}")
            return {}
    
    def get_real_time_analysis_data(self, symbols: List[str]) -> Dict:
        """
        Get comprehensive real-time data optimized for analysis.
        
        Args:
            symbols: List of stock symbols
            
        Returns:
            Dictionary with comprehensive real-time analysis data
        """
        logger.info(f"Fetching real-time analysis data for {len(symbols)} symbols...")
        
        # Get real-time quotes
        quotes = self.get_multiple_quotes(symbols)
        
        # Get market status
        market_status = self.get_market_status()
        
        # Prepare analysis data
        analysis_data = {
            'timestamp': datetime.now(),
            'market_status': market_status,
            'quotes': quotes,
            'symbols_count': len(symbols),
            'successful_fetches': len([q for q in quotes.values() if q]),
            'failed_fetches': len([q for q in quotes.values() if not q])
        }
        
        # Add summary statistics
        if quotes:
            prices = [q.get('price', 0) for q in quotes.values() if q.get('price')]
            changes = [q.get('change_percent', 0) for q in quotes.values() if q.get('change_percent')]
            
            if prices:
                analysis_data['summary'] = {
                    'avg_price': np.mean(prices),
                    'avg_change_percent': np.mean(changes),
                    'positive_movers': len([c for c in changes if c > 0]),
                    'negative_movers': len([c for c in changes if c < 0]),
                    'total_volume': sum([q.get('volume', 0) for q in quotes.values() if q.get('volume')])
                }
        
        logger.info(f"Real-time analysis data ready: {analysis_data['successful_fetches']}/{analysis_data['symbols_count']} successful")
        
        return analysis_data


def test_real_time_provider():
    """Test function for the real-time data provider."""
    print("🔄 Testing Real-Time Data Provider")
    print("=" * 50)
    
    # Initialize provider
    provider = RealTimeDataProvider()
    
    # Test symbols
    test_symbols = ['AAPL', 'MSFT', 'GOOGL']
    
    print(f"📊 Testing real-time quotes for: {', '.join(test_symbols)}")
    
    # Test individual quote
    print("\n1. Individual Quote Test:")
    quote = provider.get_real_time_quote('AAPL')
    if quote:
        print(f"   AAPL: ${quote.get('price', 'N/A')} ({quote.get('change_percent', 0):+.2f}%)")
        print(f"   Provider: {quote.get('provider', 'unknown')}")
    else:
        print("   ❌ Failed to get quote")
    
    # Test multiple quotes
    print("\n2. Multiple Quotes Test:")
    quotes = provider.get_multiple_quotes(test_symbols)
    for symbol, data in quotes.items():
        if data:
            print(f"   {symbol}: ${data.get('price', 'N/A')} ({data.get('change_percent', 0):+.2f}%)")
        else:
            print(f"   {symbol}: ❌ No data")
    
    # Test market status
    print("\n3. Market Status Test:")
    status = provider.get_market_status()
    print(f"   Market Open: {status.get('is_open', 'Unknown')}")
    print(f"   Current Time: {status.get('current_time', 'Unknown')}")
    
    # Test analysis data
    print("\n4. Analysis Data Test:")
    analysis = provider.get_real_time_analysis_data(test_symbols)
    print(f"   Success Rate: {analysis.get('successful_fetches', 0)}/{analysis.get('symbols_count', 0)}")
    if 'summary' in analysis:
        summary = analysis['summary']
        print(f"   Avg Change: {summary.get('avg_change_percent', 0):+.2f}%")
        print(f"   Positive Movers: {summary.get('positive_movers', 0)}")
    
    print("\n✅ Real-time data provider test completed!")


if __name__ == "__main__":
    test_real_time_provider()