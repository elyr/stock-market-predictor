"""
Quick test script to check data freshness throughout the day
"""

import yfinance as yf
from datetime import datetime
import time

def quick_freshness_check():
    print(f"⏰ Quick Data Freshness Check - {datetime.now().strftime('%H:%M:%S')}")
    print("-" * 50)
    
    symbols = ['AAPL', 'SPY']
    
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period='1d', interval='1m')
            
            if not hist.empty:
                latest_time = hist.index[-1]
                latest_price = hist.iloc[-1]['Close']
                latest_volume = hist.iloc[-1]['Volume']
                
                # Calculate data age
                now = datetime.now()
                data_age = (now - latest_time.replace(tzinfo=None)).total_seconds() / 60
                
                freshness = "🟢 FRESH" if data_age < 5 else "🟡 DELAYED" if data_age < 60 else "🔴 STALE"
                volume_status = "🔊 ACTIVE" if latest_volume > 0 else "🔇 NO VOLUME"
                
                print(f"{symbol}: ${latest_price:.2f} | {freshness} ({data_age:.0f}m old) | {volume_status}")
            else:
                print(f"{symbol}: ❌ No data available")
                
        except Exception as e:
            print(f"{symbol}: ❌ Error - {str(e)}")

if __name__ == "__main__":
    quick_freshness_check()