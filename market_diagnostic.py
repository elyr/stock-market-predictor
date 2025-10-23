"""
Enhanced Real-Time Market Data Test
Forces fresh data retrieval and better market status detection
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import requests
import time

def check_market_status():
    """Check if US market is currently open."""
    try:
        # Get current EST time
        est = pytz.timezone('US/Eastern')
        now_est = datetime.now(est)
        
        # Market hours: 9:30 AM - 4:00 PM EST, Monday-Friday
        market_open = now_est.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_est.replace(hour=16, minute=0, second=0, microsecond=0)
        
        is_weekday = now_est.weekday() < 5  # 0-4 are Monday-Friday
        is_market_hours = market_open <= now_est <= market_close
        
        return {
            'current_est': now_est,
            'is_weekday': is_weekday,
            'is_market_hours': is_market_hours,
            'is_open': is_weekday and is_market_hours,
            'market_open': market_open,
            'market_close': market_close,
            'time_to_open': max(0, (market_open - now_est).total_seconds()) if now_est < market_open else 0,
            'time_to_close': max(0, (market_close - now_est).total_seconds()) if now_est < market_close else 0
        }
    except Exception as e:
        print(f"Error checking market status: {e}")
        return {'is_open': False}

def get_live_quote(symbol):
    """Get the most current quote possible."""
    try:
        ticker = yf.Ticker(symbol)
        
        # Try multiple methods to get the freshest data
        
        # Method 1: Get today's data with 1-minute intervals
        hist_1m = ticker.history(period='1d', interval='1m', prepost=True)
        
        # Method 2: Get recent 5-day data to compare
        hist_5d = ticker.history(period='5d', interval='1d')
        
        # Method 3: Get ticker info for additional data
        info = ticker.info
        
        result = {
            'symbol': symbol,
            'timestamp': datetime.now(),
            'data_sources': []
        }
        
        # Use 1-minute data if available and recent
        if not hist_1m.empty:
            latest_1m = hist_1m.iloc[-1]
            latest_time = hist_1m.index[-1]
            
            # Check if data is recent (within last 5 minutes)
            time_diff = datetime.now() - latest_time.replace(tzinfo=None)
            
            result.update({
                'price': float(latest_1m['Close']),
                'open': float(latest_1m['Open']),
                'high': float(latest_1m['High']),
                'low': float(latest_1m['Low']),
                'volume': int(latest_1m['Volume']),
                'data_time': latest_time,
                'data_age_minutes': time_diff.total_seconds() / 60,
                'intraday_points': len(hist_1m)
            })
            result['data_sources'].append(f'1m_data_{len(hist_1m)}_points')
            
            # Calculate day's change
            if len(hist_1m) > 1:
                day_open = hist_1m.iloc[0]['Open']
                current_price = latest_1m['Close']
                result['change'] = float(current_price - day_open)
                result['change_percent'] = ((current_price - day_open) / day_open) * 100
            else:
                result['change'] = 0
                result['change_percent'] = 0
        
        # Add info data if available
        if info:
            result.update({
                'market_cap': info.get('marketCap', 0),
                'avg_volume': info.get('averageVolume', 0),
                'pe_ratio': info.get('trailingPE', 0),
                'sector': info.get('sector', 'Unknown')
            })
            result['data_sources'].append('yahoo_info')
            
            # Calculate volume ratio
            if result.get('volume', 0) > 0 and result.get('avg_volume', 0) > 0:
                result['volume_ratio'] = result['volume'] / result['avg_volume']
            else:
                result['volume_ratio'] = 0
        
        # Add 5-day comparison
        if not hist_5d.empty and len(hist_5d) >= 2:
            prev_close = hist_5d.iloc[-2]['Close']
            current_price = result.get('price', prev_close)
            result['prev_day_change'] = float(current_price - prev_close)
            result['prev_day_change_percent'] = ((current_price - prev_close) / prev_close) * 100
            result['data_sources'].append('5d_comparison')
        
        return result
        
    except Exception as e:
        print(f"Error getting quote for {symbol}: {e}")
        return {'symbol': symbol, 'error': str(e)}

def test_live_market_data():
    """Test live market data with detailed diagnostics."""
    print("🔍 ENHANCED MARKET DATA DIAGNOSTIC")
    print("=" * 60)
    
    # Check market status
    market_status = check_market_status()
    
    print(f"🕒 Market Status Check:")
    print(f"   Current EST Time: {market_status.get('current_est', 'Unknown')}")
    print(f"   Is Weekday: {market_status.get('is_weekday', False)}")
    print(f"   Is Market Hours: {market_status.get('is_market_hours', False)}")
    print(f"   Market Open: {'✅ YES' if market_status.get('is_open', False) else '❌ NO'}")
    
    if not market_status.get('is_open', False):
        if market_status.get('time_to_open', 0) > 0:
            hours = int(market_status['time_to_open'] // 3600)
            minutes = int((market_status['time_to_open'] % 3600) // 60)
            print(f"   Time to Open: {hours}h {minutes}m")
        elif market_status.get('time_to_close', 0) > 0:
            hours = int(market_status['time_to_close'] // 3600)
            minutes = int((market_status['time_to_close'] % 3600) // 60)
            print(f"   Time to Close: {hours}h {minutes}m")
    
    print(f"\n📊 Live Data Test:")
    print("-" * 60)
    
    # Test symbols
    test_symbols = ['AAPL', 'SPY', 'QQQ', 'TSLA', 'MSFT']
    
    for symbol in test_symbols:
        print(f"\n🔍 Testing {symbol}:")
        
        quote = get_live_quote(symbol)
        
        if 'error' in quote:
            print(f"   ❌ Error: {quote['error']}")
            continue
        
        price = quote.get('price', 0)
        change_pct = quote.get('change_percent', 0)
        volume = quote.get('volume', 0)
        volume_ratio = quote.get('volume_ratio', 0)
        data_age = quote.get('data_age_minutes', 0)
        intraday_points = quote.get('intraday_points', 0)
        
        # Status indicators
        volume_emoji = "🔊" if volume > 1000000 else "📊" if volume > 100000 else "🔇"
        price_emoji = "🟢" if change_pct > 0 else "🔴" if change_pct < 0 else "⚪"
        freshness_emoji = "🟢" if data_age < 2 else "🟡" if data_age < 10 else "🔴"
        
        print(f"   {price_emoji} Price: ${price:.2f} ({change_pct:+.2f}%)")
        print(f"   {volume_emoji} Volume: {volume:,} ({volume_ratio:.1f}x avg)")
        print(f"   {freshness_emoji} Data Age: {data_age:.1f} minutes ({intraday_points} data points)")
        print(f"   📡 Sources: {', '.join(quote.get('data_sources', []))}")
        
        # Diagnose issues
        if volume == 0:
            print(f"   ⚠️ ISSUE: Zero volume detected")
        if change_pct == 0:
            print(f"   ⚠️ ISSUE: No price movement detected")
        if data_age > 10:
            print(f"   ⚠️ ISSUE: Data is stale (>{data_age:.0f} minutes old)")
        if intraday_points < 10:
            print(f"   ⚠️ ISSUE: Limited intraday data ({intraday_points} points)")
    
    print(f"\n🔍 DIAGNOSIS:")
    print("-" * 30)
    
    if market_status.get('is_open', False):
        print("✅ Market should be open - if seeing zero volume/change:")
        print("   • Yahoo Finance might have delayed data")
        print("   • Try running during peak trading hours (10 AM - 3 PM EST)")
        print("   • Some stocks might be halted or have low activity")
        print("   • Network issues might be affecting data retrieval")
    else:
        print("ℹ️ Market is currently closed:")
        print("   • Zero volume and changes are normal")
        print("   • Prices show last closing values")
        print("   • For live testing, run during market hours (9:30 AM - 4 PM EST)")
    
    print(f"\n💡 RECOMMENDATIONS:")
    print("-" * 30)
    print("• Test during market hours for best results")
    print("• Use highly liquid stocks (AAPL, SPY, QQQ)")
    print("• Check multiple symbols to confirm data quality")
    print("• Consider paid APIs for guaranteed real-time data")

if __name__ == "__main__":
    test_live_market_data()