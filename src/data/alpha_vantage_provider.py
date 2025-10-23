"""
Alpha Vantage Real-Time Data Provider
Better data quality than Yahoo Finance for serious analysis
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

class AlphaVantageProvider:
    """
    Professional-grade data provider for better real-time analysis
    """
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or "demo"  # Use demo key for testing
        self.base_url = "https://www.alphavantage.co/query"
        self.last_request_time = 0
        self.request_delay = 12  # 5 requests per minute limit
        
    def _rate_limit(self):
        """Respect API rate limits"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self.last_request_time = time.time()
    
    def get_quote(self, symbol: str) -> Dict:
        """Get real-time quote with better data quality"""
        self._rate_limit()
        
        params = {
            'function': 'GLOBAL_QUOTE',
            'symbol': symbol,
            'apikey': self.api_key
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            data = response.json()
            
            if 'Global Quote' in data:
                quote = data['Global Quote']
                
                # Parse the quote data
                return {
                    'symbol': quote.get('01. symbol', symbol),
                    'price': float(quote.get('05. price', 0)),
                    'change': float(quote.get('09. change', 0)),
                    'change_percent': quote.get('10. change percent', '0%').replace('%', ''),
                    'volume': int(quote.get('06. volume', 0)),
                    'previous_close': float(quote.get('08. previous close', 0)),
                    'open': float(quote.get('02. open', 0)),
                    'high': float(quote.get('03. high', 0)),
                    'low': float(quote.get('04. low', 0)),
                    'latest_trading_day': quote.get('07. latest trading day', ''),
                    'timestamp': datetime.now(),
                    'source': 'AlphaVantage'
                }
            else:
                print(f"⚠️ Alpha Vantage API issue: {data}")
                return None
                
        except Exception as e:
            print(f"❌ Alpha Vantage error for {symbol}: {e}")
            return None
    
    def get_intraday_data(self, symbol: str, interval: str = '1min') -> pd.DataFrame:
        """Get intraday data for technical analysis"""
        self._rate_limit()
        
        params = {
            'function': 'TIME_SERIES_INTRADAY',
            'symbol': symbol,
            'interval': interval,
            'apikey': self.api_key,
            'outputsize': 'compact'  # Last 100 data points
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            data = response.json()
            
            time_series_key = f'Time Series ({interval})'
            
            if time_series_key in data:
                df = pd.DataFrame.from_dict(data[time_series_key], orient='index')
                df.index = pd.to_datetime(df.index)
                df = df.astype(float)
                df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                df = df.sort_index()
                return df
            else:
                print(f"⚠️ No intraday data: {data}")
                return pd.DataFrame()
                
        except Exception as e:
            print(f"❌ Intraday data error for {symbol}: {e}")
            return pd.DataFrame()


def test_alpha_vantage_quality():
    """Test Alpha Vantage data quality vs Yahoo"""
    print("🔬 Testing Alpha Vantage vs Yahoo Finance Data Quality")
    print("=" * 60)
    
    # Initialize providers
    av_provider = AlphaVantageProvider()
    
    test_symbols = ['AAPL', 'MSFT', 'SPY']
    
    print(f"🕐 Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)
    
    for symbol in test_symbols:
        print(f"\n📊 Testing {symbol}:")
        print("-" * 20)
        
        # Test Alpha Vantage
        print("🔵 Alpha Vantage:")
        av_quote = av_provider.get_quote(symbol)
        if av_quote:
            print(f"   Price: ${av_quote['price']:.2f}")
            print(f"   Volume: {av_quote['volume']:,}")
            print(f"   Change: {av_quote['change_percent']}%")
            print(f"   Trading Day: {av_quote['latest_trading_day']}")
        else:
            print("   ❌ Failed to get data")
        
        # Test Yahoo Finance for comparison
        print("🟡 Yahoo Finance:")
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period='1d', interval='1m')
            
            if not hist.empty:
                latest_price = hist.iloc[-1]['Close']
                latest_volume = hist.iloc[-1]['Volume']
                latest_time = hist.index[-1]
                
                # Calculate data age
                now = datetime.now()
                data_age = (now - latest_time.replace(tzinfo=None)).total_seconds() / 60
                
                print(f"   Price: ${latest_price:.2f}")
                print(f"   Volume: {latest_volume:,.0f}")
                print(f"   Data Age: {data_age:.0f} minutes")
            else:
                print("   ❌ No data available")
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    print(f"\n{'='*60}")
    print("💡 Analysis:")
    print("  - Alpha Vantage: Professional-grade, 15-min delay max")
    print("  - Yahoo Finance: Free but often hours delayed")
    print("  - For precise analysis, Alpha Vantage is recommended")


if __name__ == "__main__":
    test_alpha_vantage_quality()