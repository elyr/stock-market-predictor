"""
Alpha Vantage Data Provider Module
Professional-grade data collection using Alpha Vantage API exclusively
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time
import logging
from typing import Dict, List, Optional, Union
import json
import warnings
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from dotenv import load_dotenv

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)
load_dotenv()


class AlphaVantageDataProvider:
    """
    Professional real-time data provider using Alpha Vantage API exclusively.
    """
    
    def __init__(self, alpha_vantage_key=None):
        """
        Initialize with Alpha Vantage API key.
        
        Args:
            alpha_vantage_key: Alpha Vantage API key (from .env if not provided)
        """
        self.alpha_vantage_key = alpha_vantage_key or os.getenv('ALPHA_VANTAGE_API_KEY')
        
        if not self.alpha_vantage_key:
            raise ValueError("Alpha Vantage API key is required. Set ALPHA_VANTAGE_API_KEY in .env file")
        
        self.base_url = "https://www.alphavantage.co/query"
        
        # Rate limiting (5 requests per minute for free tier)
        self.last_request_time = 0
        self.min_request_interval = 12  # 12 seconds between requests
        
        # Cache for real-time data
        self.real_time_cache = {}
        self.cache_expiry = 30  # Cache expires in 30 seconds
        
        print(f"🔑 Alpha Vantage Data Provider initialized with key: {self.alpha_vantage_key[:8]}***")
    
    def _rate_limit(self):
        """Enforce rate limiting for API requests"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval:
            sleep_time = self.min_request_interval - elapsed
            print(f"⏳ Rate limiting: waiting {sleep_time:.1f}s...")
            time.sleep(sleep_time)
        self.last_request_time = time.time()
    
    def _is_cache_valid(self, symbol: str) -> bool:
        """Check if cached data is still valid"""
        if symbol not in self.real_time_cache:
            return False
        
        cache_time = self.real_time_cache[symbol].get('timestamp')
        if not cache_time:
            return False
        
        age_seconds = (datetime.now() - cache_time).total_seconds()
        return age_seconds < self.cache_expiry
    
    def get_real_time_quote(self, symbol: str) -> Optional[Dict]:
        """
        Get real-time quote from Alpha Vantage
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            
        Returns:
            Dict with quote data or None if failed
        """
        # Check cache first
        if self._is_cache_valid(symbol):
            return self.real_time_cache[symbol]['data']
        
        self._rate_limit()
        
        params = {
            'function': 'GLOBAL_QUOTE',
            'symbol': symbol,
            'apikey': self.alpha_vantage_key
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=15)
            data = response.json()
            
            if 'Global Quote' in data:
                quote = data['Global Quote']
                
                # Parse the quote data
                quote_data = {
                    'symbol': quote.get('01. symbol', symbol),
                    'price': float(quote.get('05. price', 0)),
                    'change': float(quote.get('09. change', 0)),
                    'change_percent': float(quote.get('10. change percent', '0%').replace('%', '')),
                    'volume': int(quote.get('06. volume', 0)),
                    'previous_close': float(quote.get('08. previous close', 0)),
                    'open': float(quote.get('02. open', 0)),
                    'high': float(quote.get('03. high', 0)),
                    'low': float(quote.get('04. low', 0)),
                    'latest_trading_day': quote.get('07. latest trading day', ''),
                    'timestamp': datetime.now(),
                    'source': 'Alpha Vantage',
                    'provider': 'alpha_vantage'
                }
                
                # Cache the result
                self.real_time_cache[symbol] = {
                    'data': quote_data,
                    'timestamp': datetime.now()
                }
                
                return quote_data
            else:
                error_msg = data.get('Information', data.get('Error Message', 'Unknown error'))
                print(f"⚠️ Alpha Vantage API issue for {symbol}: {error_msg}")
                return None
                
        except Exception as e:
            print(f"❌ Error getting quote for {symbol}: {e}")
            return None
    
    def get_intraday_data(self, symbol: str, interval: str = '5min', outputsize: str = 'compact') -> pd.DataFrame:
        """
        Get intraday data from Alpha Vantage
        
        Args:
            symbol: Stock symbol
            interval: Time interval (1min, 5min, 15min, 30min, 60min)
            outputsize: 'compact' (last 100 points) or 'full'
            
        Returns:
            DataFrame with OHLCV data
        """
        self._rate_limit()
        
        params = {
            'function': 'TIME_SERIES_INTRADAY',
            'symbol': symbol,
            'interval': interval,
            'apikey': self.alpha_vantage_key,
            'outputsize': outputsize
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=15)
            data = response.json()
            
            time_series_key = f'Time Series ({interval})'
            
            if time_series_key in data:
                df = pd.DataFrame.from_dict(data[time_series_key], orient='index')
                df.index = pd.to_datetime(df.index)
                df = df.astype(float)
                df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                df = df.sort_index()
                
                print(f"✅ {symbol}: Retrieved {len(df)} intraday data points ({interval})")
                return df
            else:
                error_msg = data.get('Information', data.get('Error Message', 'Unknown error'))
                print(f"⚠️ No intraday data for {symbol}: {error_msg}")
                return pd.DataFrame()
                
        except Exception as e:
            print(f"❌ Error getting intraday data for {symbol}: {e}")
            return pd.DataFrame()
    
    def get_daily_data(self, symbol: str, outputsize: str = 'compact') -> pd.DataFrame:
        """
        Get daily historical data from Alpha Vantage
        
        Args:
            symbol: Stock symbol
            outputsize: 'compact' (last 100 days) or 'full'
            
        Returns:
            DataFrame with daily OHLCV data
        """
        self._rate_limit()
        
        params = {
            'function': 'TIME_SERIES_DAILY',
            'symbol': symbol,
            'apikey': self.alpha_vantage_key,
            'outputsize': outputsize
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=15)
            data = response.json()
            
            if 'Time Series (Daily)' in data:
                df = pd.DataFrame.from_dict(data['Time Series (Daily)'], orient='index')
                df.index = pd.to_datetime(df.index)
                df = df.astype(float)
                df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                df = df.sort_index()
                
                print(f"✅ {symbol}: Retrieved {len(df)} daily data points")
                return df
            else:
                error_msg = data.get('Information', data.get('Error Message', 'Unknown error'))
                print(f"⚠️ No daily data for {symbol}: {error_msg}")
                return pd.DataFrame()
                
        except Exception as e:
            print(f"❌ Error getting daily data for {symbol}: {e}")
            return pd.DataFrame()
    
    def get_multiple_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Get real-time quotes for multiple symbols concurrently
        
        Args:
            symbols: List of stock symbols
            
        Returns:
            Dict mapping symbols to their quote data
        """
        print(f"📊 Getting quotes for {len(symbols)} symbols...")
        
        quotes = {}
        
        # Process symbols sequentially due to rate limits
        for i, symbol in enumerate(symbols, 1):
            print(f"   {i}/{len(symbols)}: {symbol}")
            quote = self.get_real_time_quote(symbol)
            if quote:
                quotes[symbol] = quote
        
        return quotes
    
    def get_market_status(self) -> Dict:
        """
        Get current market status
        
        Returns:
            Dict with market status information
        """
        now = datetime.now()
        
        # Market hours: 9:30 AM - 4:00 PM EST, Monday-Friday
        # Convert to EST
        est = now.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-5)))
        
        is_weekday = est.weekday() < 5  # Monday = 0, Friday = 4
        market_open = est.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = est.replace(hour=16, minute=0, second=0, microsecond=0)
        
        is_market_hours = market_open <= est <= market_close
        is_market_open = is_weekday and is_market_hours
        
        # Calculate time to next open/close
        if is_market_open:
            time_to_close = (market_close - est).total_seconds()
            next_event = f"Market closes in {time_to_close/3600:.1f} hours"
        else:
            if est < market_open:
                time_to_open = (market_open - est).total_seconds()
                next_event = f"Market opens in {time_to_open/3600:.1f} hours"
            else:
                # After hours, calculate next day
                next_day = est + timedelta(days=1)
                next_open = next_day.replace(hour=9, minute=30, second=0, microsecond=0)
                time_to_open = (next_open - est).total_seconds()
                next_event = f"Market opens in {time_to_open/3600:.1f} hours"
        
        return {
            'is_open': is_market_open,
            'current_time': est.strftime('%Y-%m-%d %H:%M:%S EST'),
            'next_event': next_event,
            'is_weekday': is_weekday,
            'is_market_hours': is_market_hours
        }
    
    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate technical indicators for the dataframe
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            DataFrame with additional technical indicators
        """
        if df.empty or len(df) < 20:
            return df
        
        # Simple Moving Averages
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        
        # Exponential Moving Averages
        df['EMA_12'] = df['Close'].ewm(span=12).mean()
        df['EMA_26'] = df['Close'].ewm(span=26).mean()
        
        # MACD
        df['MACD'] = df['EMA_12'] - df['EMA_26']
        df['MACD_Signal'] = df['MACD'].ewm(span=9).mean()
        df['MACD_Histogram'] = df['MACD'] - df['MACD_Signal']
        
        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # Bollinger Bands
        df['BB_Middle'] = df['Close'].rolling(window=20).mean()
        bb_std = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['BB_Middle'] + (bb_std * 2)
        df['BB_Lower'] = df['BB_Middle'] - (bb_std * 2)
        df['BB_Position'] = (df['Close'] - df['BB_Lower']) / (df['BB_Upper'] - df['BB_Lower'])
        
        # Volume indicators
        df['Volume_SMA'] = df['Volume'].rolling(window=20).mean()
        df['Volume_Ratio'] = df['Volume'] / df['Volume_SMA']
        
        return df


# Alias for backward compatibility
RealTimeDataProvider = AlphaVantageDataProvider


def test_alpha_vantage_provider():
    """Test the Alpha Vantage data provider"""
    print("🧪 Testing Alpha Vantage Data Provider")
    print("=" * 50)
    
    provider = AlphaVantageDataProvider()
    
    # Test symbols
    test_symbols = ['AAPL', 'MSFT', 'SPY']
    
    print(f"\n📊 Testing real-time quotes...")
    quotes = provider.get_multiple_quotes(test_symbols)
    
    for symbol, quote in quotes.items():
        if quote:
            print(f"✅ {symbol}: ${quote['price']:.2f} | "
                  f"Change: {quote['change_percent']:+.2f}% | "
                  f"Volume: {quote['volume']:,}")
    
    print(f"\n📈 Testing intraday data...")
    df = provider.get_intraday_data('AAPL', '5min')
    if not df.empty:
        print(f"✅ AAPL intraday: {len(df)} data points from {df.index[0]} to {df.index[-1]}")
        
        # Test technical indicators
        df = provider.calculate_technical_indicators(df)
        if 'RSI' in df.columns:
            latest_rsi = df['RSI'].iloc[-1]
            print(f"✅ Latest RSI: {latest_rsi:.1f}")
    
    print(f"\n🕐 Market status:")
    status = provider.get_market_status()
    print(f"   Status: {'🟢 OPEN' if status['is_open'] else '🔴 CLOSED'}")
    print(f"   Time: {status['current_time']}")
    print(f"   {status['next_event']}")


if __name__ == "__main__":
    test_alpha_vantage_provider()