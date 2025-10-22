"""
Simple Real-Time Market Data Test
Demonstrates enhanced real-time capabilities
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SimpleRealTimeAnalyzer:
    """Simplified real-time analyzer for demonstration."""
    
    def __init__(self):
        self.cache = {}
        self.cache_expiry = 30  # 30 seconds
    
    def get_real_time_quote(self, symbol: str) -> dict:
        """Get real-time quote using Yahoo Finance."""
        try:
            # Check cache
            cache_key = f"rt_{symbol}"
            if cache_key in self.cache:
                data, timestamp = self.cache[cache_key]
                if (datetime.now() - timestamp).seconds < self.cache_expiry:
                    return data
            
            # Fetch fresh data
            ticker = yf.Ticker(symbol)
            
            # Get current data
            info = ticker.info
            hist = ticker.history(period='1d', interval='1m')
            
            if hist.empty:
                return {}
            
            latest = hist.iloc[-1]
            
            quote_data = {
                'symbol': symbol,
                'price': float(latest['Close']),
                'open': float(latest['Open']),
                'high': float(latest['High']),
                'low': float(latest['Low']),
                'volume': int(latest['Volume']),
                'timestamp': datetime.now(),
                'change': float(latest['Close'] - latest['Open']),
                'change_percent': ((latest['Close'] - latest['Open']) / latest['Open']) * 100,
                'market_cap': info.get('marketCap', 0),
                'pe_ratio': info.get('trailingPE', 0),
                'avg_volume': info.get('averageVolume', 0)
            }
            
            # Add volume ratio if available
            if quote_data['avg_volume'] > 0:
                quote_data['volume_ratio'] = quote_data['volume'] / quote_data['avg_volume']
            else:
                quote_data['volume_ratio'] = 1.0
            
            # Cache result
            self.cache[cache_key] = (quote_data, datetime.now())
            
            return quote_data
            
        except Exception as e:
            logger.error(f"Error getting quote for {symbol}: {str(e)}")
            return {}
    
    def get_multiple_quotes(self, symbols: list, max_workers: int = 5) -> dict:
        """Get quotes for multiple symbols concurrently."""
        results = {}
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_symbol = {
                executor.submit(self.get_real_time_quote, symbol): symbol 
                for symbol in symbols
            }
            
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    quote_data = future.result(timeout=15)
                    results[symbol] = quote_data
                except Exception as e:
                    logger.error(f"Error processing {symbol}: {str(e)}")
                    results[symbol] = {}
        
        return results
    
    def analyze_real_time_opportunities(self, symbols: list):
        """Analyze real-time trading opportunities."""
        print("📊 REAL-TIME MARKET ANALYSIS")
        print("=" * 60)
        print(f"🕒 Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📋 Analyzing {len(symbols)} symbols...")
        print()
        
        # Get real-time data
        quotes = self.get_multiple_quotes(symbols)
        
        # Analyze each symbol
        opportunities = []
        alerts = []
        
        print("📈 REAL-TIME STOCK ANALYSIS")
        print("-" * 80)
        print(f"{'Symbol':<8} {'Price':<10} {'Change%':<10} {'Volume':<12} {'Signals':<20}")
        print("-" * 80)
        
        for symbol in symbols:
            quote = quotes.get(symbol, {})
            
            if not quote:
                print(f"❌ {symbol:<8} No data available")
                continue
            
            # Calculate signals
            signals = self._analyze_quote(quote)
            analysis = self._get_analysis_summary(quote, signals)
            
            # Display
            price = quote.get('price', 0)
            change_pct = quote.get('change_percent', 0)
            volume = quote.get('volume', 0)
            volume_ratio = quote.get('volume_ratio', 1.0)
            
            # Format display
            price_emoji = "🟢" if change_pct > 0 else "🔴" if change_pct < 0 else "⚪"
            volume_str = f"{volume/1000000:.1f}M" if volume > 1000000 else f"{volume/1000:.0f}K"
            
            # Key signals for display
            key_signals = signals[:2] if len(signals) <= 2 else signals[:1]
            signals_str = ", ".join(key_signals) if key_signals else "NEUTRAL"
            
            print(f"{price_emoji} {symbol:<8} ${price:<9.2f} {change_pct:+8.2f}% {volume_str:<11} {signals_str}")
            
            # Check for opportunities
            if analysis['opportunity_score'] > 70:
                opportunities.append({
                    'symbol': symbol,
                    'score': analysis['opportunity_score'],
                    'price': price,
                    'change_percent': change_pct,
                    'signals': signals
                })
            
            # Check for alerts
            if abs(change_pct) > 3 or volume_ratio > 2:
                alert_type = "High Movement" if abs(change_pct) > 3 else "High Volume"
                alerts.append({
                    'symbol': symbol,
                    'type': alert_type,
                    'value': f"{change_pct:+.2f}%" if abs(change_pct) > 3 else f"{volume_ratio:.1f}x volume"
                })
        
        # Display opportunities
        print(f"\n🎯 HIGH-PROBABILITY OPPORTUNITIES")
        print("-" * 50)
        if opportunities:
            for opp in sorted(opportunities, key=lambda x: x['score'], reverse=True):
                print(f"⭐ {opp['symbol']}: Score {opp['score']:.0f} - ${opp['price']:.2f} ({opp['change_percent']:+.2f}%)")
                print(f"   Signals: {', '.join(opp['signals'][:3])}")
        else:
            print("   No high-probability opportunities detected at this time")
        
        # Display alerts
        print(f"\n🚨 MARKET ALERTS")
        print("-" * 30)
        if alerts:
            for alert in alerts:
                print(f"⚠️ {alert['symbol']}: {alert['type']} - {alert['value']}")
        else:
            print("   No active alerts")
        
        # Summary statistics
        successful_quotes = len([q for q in quotes.values() if q])
        total_volume = sum([q.get('volume', 0) for q in quotes.values() if q])
        avg_change = np.mean([q.get('change_percent', 0) for q in quotes.values() if q])
        positive_movers = len([q for q in quotes.values() if q.get('change_percent', 0) > 0])
        
        print(f"\n📊 MARKET SUMMARY")
        print("-" * 30)
        print(f"Data Success Rate: {successful_quotes}/{len(symbols)} ({(successful_quotes/len(symbols)*100):.1f}%)")
        print(f"Average Change: {avg_change:+.2f}%")
        print(f"Positive Movers: {positive_movers}/{successful_quotes}")
        print(f"Total Volume: {total_volume/1000000:.0f}M shares")
        print(f"Market Sentiment: {'BULLISH' if avg_change > 0.5 else 'BEARISH' if avg_change < -0.5 else 'NEUTRAL'}")
        
        return {
            'quotes': quotes,
            'opportunities': opportunities,
            'alerts': alerts,
            'summary': {
                'avg_change': avg_change,
                'positive_movers': positive_movers,
                'total_analyzed': successful_quotes
            }
        }
    
    def _analyze_quote(self, quote: dict) -> list:
        """Analyze a quote and generate signals."""
        signals = []
        
        change_pct = quote.get('change_percent', 0)
        volume_ratio = quote.get('volume_ratio', 1.0)
        price = quote.get('price', 0)
        
        # Price movement signals
        if change_pct > 3:
            signals.append("STRONG_UP")
        elif change_pct > 1:
            signals.append("MODERATE_UP")
        elif change_pct > 0:
            signals.append("SLIGHT_UP")
        elif change_pct < -3:
            signals.append("STRONG_DOWN")
        elif change_pct < -1:
            signals.append("MODERATE_DOWN")
        elif change_pct < 0:
            signals.append("SLIGHT_DOWN")
        
        # Volume signals
        if volume_ratio > 3:
            signals.append("VERY_HIGH_VOLUME")
        elif volume_ratio > 2:
            signals.append("HIGH_VOLUME")
        elif volume_ratio > 1.5:
            signals.append("ELEVATED_VOLUME")
        
        # Momentum signals
        if abs(change_pct) > 2 and volume_ratio > 1.5:
            signals.append("STRONG_MOMENTUM")
        elif abs(change_pct) > 1 and volume_ratio > 1.2:
            signals.append("MOMENTUM")
        
        return signals
    
    def _get_analysis_summary(self, quote: dict, signals: list) -> dict:
        """Get analysis summary for a quote."""
        change_pct = quote.get('change_percent', 0)
        volume_ratio = quote.get('volume_ratio', 1.0)
        
        # Calculate opportunity score
        score = 50  # Base score
        
        # Price factor
        if abs(change_pct) > 2:
            score += 20
        elif abs(change_pct) > 1:
            score += 10
        elif abs(change_pct) > 0.5:
            score += 5
        
        # Volume factor
        if volume_ratio > 2:
            score += 15
        elif volume_ratio > 1.5:
            score += 10
        elif volume_ratio > 1.2:
            score += 5
        
        # Direction factor (favor upward movement)
        if change_pct > 0:
            score += 10
        
        # Signal strength factor
        strong_signals = len([s for s in signals if 'STRONG' in s or 'HIGH' in s])
        score += strong_signals * 5
        
        return {
            'opportunity_score': min(100, max(0, score)),
            'signals': signals,
            'change_percent': change_pct,
            'volume_ratio': volume_ratio
        }


def main():
    """Main function."""
    print("🚀 REAL-TIME MARKET ANALYZER (Enhanced)")
    print("=" * 50)
    
    # Test symbols
    default_symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM', 'V', 'UNH']
    
    analyzer = SimpleRealTimeAnalyzer()
    
    print("Analysis Options:")
    print("1. Quick analysis (default symbols)")
    print("2. Custom symbols")
    print("3. Continuous monitoring")
    
    try:
        choice = input("\nSelect option (1-3, default 1): ").strip() or "1"
        
        symbols = default_symbols
        
        if choice == "2":
            custom_input = input("Enter symbols (comma-separated): ").strip()
            if custom_input:
                symbols = [s.strip().upper() for s in custom_input.split(',')]
        
        if choice == "3":
            interval = input("Monitoring interval in minutes (default 2): ").strip()
            interval_minutes = int(interval) if interval.isdigit() else 2
            
            print(f"\n🔄 Starting continuous monitoring...")
            print(f"⏰ Update every {interval_minutes} minutes")
            print("Press Ctrl+C to stop\n")
            
            while True:
                try:
                    results = analyzer.analyze_real_time_opportunities(symbols)
                    print(f"\n⏰ Next update in {interval_minutes} minutes...")
                    print("=" * 60)
                    time.sleep(interval_minutes * 60)
                except KeyboardInterrupt:
                    print("\n🛑 Monitoring stopped")
                    break
        else:
            # Single analysis
            results = analyzer.analyze_real_time_opportunities(symbols)
            
            print(f"\n✅ Analysis completed successfully!")
            print(f"📊 Found {len(results['opportunities'])} opportunities and {len(results['alerts'])} alerts")
    
    except KeyboardInterrupt:
        print("\n👋 Stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")


if __name__ == "__main__":
    main()