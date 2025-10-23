"""
Enhanced Real-Time Analysis with Alpha Vantage
Uses Alpha Vantage API exclusively for high-quality data
"""

import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import time
from typing import Dict, List, Optional
import requests
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class EnhancedRealTimeAnalyzer:
    """
    Professional real-time analysis with multiple data sources
    """
    
    def __init__(self, alpha_vantage_key: str = None):
        self.alpha_vantage_key = alpha_vantage_key or os.getenv('ALPHA_VANTAGE_API_KEY') or "demo"
        self.data_sources = ['alpha_vantage']
        self.cache = {}
        self.cache_expiry = 300  # 5 minutes cache to avoid rate limits
        print(f"🔑 Using Alpha Vantage API key: {self.alpha_vantage_key[:8]}***")
        
    def get_alpha_vantage_quote(self, symbol: str) -> Optional[Dict]:
        """Get quote from Alpha Vantage (better quality)"""
        
        # Check cache first
        cache_key = f"av_{symbol}"
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            age = (datetime.now() - timestamp).total_seconds()
            if age < self.cache_expiry:
                print(f"📋 Using cached data for {symbol} (age: {age:.0f}s)")
                return cached_data
        
        try:
            url = "https://www.alphavantage.co/query"
            params = {
                'function': 'GLOBAL_QUOTE',
                'symbol': symbol,
                'apikey': self.alpha_vantage_key
            }
            
            # Add rate limiting
            time.sleep(12)  # 12 seconds between requests
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if 'Global Quote' in data:
                quote = data['Global Quote']
                
                quote_data = {
                    'symbol': symbol,
                    'price': float(quote.get('05. price', 0)),
                    'change': float(quote.get('09. change', 0)),
                    'change_percent': float(quote.get('10. change percent', '0%').replace('%', '')),
                    'volume': int(quote.get('06. volume', 0)),
                    'open': float(quote.get('02. open', 0)),
                    'high': float(quote.get('03. high', 0)),
                    'low': float(quote.get('04. low', 0)),
                    'previous_close': float(quote.get('08. previous close', 0)),
                    'latest_trading_day': quote.get('07. latest trading day', ''),
                    'timestamp': datetime.now(),
                    'source': 'AlphaVantage',
                    'data_quality': 'HIGH'
                }
                
                # Cache the result
                self.cache[cache_key] = (quote_data, datetime.now())
                
                return quote_data
            else:
                error_msg = data.get('Information', 'Unknown error')
                print(f"⚠️ Alpha Vantage issue for {symbol}: {error_msg}")
                return None
                
        except Exception as e:
            print(f"Alpha Vantage error for {symbol}: {e}")
            return None
    
    def get_best_quote(self, symbol: str) -> Optional[Dict]:
        """Get quote from Alpha Vantage exclusively"""
        
        # Use Alpha Vantage only
        av_quote = self.get_alpha_vantage_quote(symbol)
        if av_quote:
            return av_quote
        
        print(f"❌ No data available for {symbol} from Alpha Vantage")
        return None
    
    def analyze_opportunities(self, symbols: List[str]) -> List[Dict]:
        """Enhanced opportunity analysis with Alpha Vantage data"""
        print(f"🔍 Enhanced Real-Time Analysis - {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 60)
        
        opportunities = []
        
        # Get quotes concurrently
        with ThreadPoolExecutor(max_workers=5) as executor:
            quote_futures = {
                executor.submit(self.get_best_quote, symbol): symbol 
                for symbol in symbols
            }
            
            for future in quote_futures:
                symbol = quote_futures[future]
                quote = future.result()
                
                if quote:
                    # Enhanced scoring with data quality consideration
                    score = self.calculate_enhanced_score(quote)
                    
                    opportunity = {
                        'symbol': symbol,
                        'price': quote['price'],
                        'volume': quote.get('volume', 0),
                        'change_percent': quote.get('change_percent', 0),
                        'score': score,
                        'data_source': quote['source'],
                        'data_quality': quote['data_quality'],
                        'analysis_time': datetime.now()
                    }
                    
                    if quote['data_quality'] == 'LOW':
                        opportunity['warning'] = f"Data is {quote.get('data_age_minutes', 0):.0f} minutes old"
                    
                    opportunities.append(opportunity)
        
        # Sort by score
        opportunities.sort(key=lambda x: x['score'], reverse=True)
        
        # Display results
        self.display_enhanced_results(opportunities)
        
        return opportunities
    
    def calculate_enhanced_score(self, quote: Dict) -> float:
        """Enhanced scoring that considers data quality"""
        base_score = 50  # Base score
        
        # Volume factor (more volume = more interest)
        volume = quote.get('volume', 0)
        if volume > 1000000:  # High volume
            base_score += 20
        elif volume > 100000:  # Medium volume
            base_score += 10
        elif volume == 0:  # No volume (stale data)
            base_score -= 30
        
        # Price change factor
        change_percent = abs(quote.get('change_percent', 0))
        if change_percent > 3:  # Significant movement
            base_score += 25
        elif change_percent > 1:  # Moderate movement
            base_score += 15
        
        # Data quality factor
        data_quality = quote.get('data_quality', 'MEDIUM')
        if data_quality == 'HIGH':
            base_score += 10
        elif data_quality == 'LOW':
            base_score -= 20
        
        return max(0, min(100, base_score))
    
    def display_enhanced_results(self, opportunities: List[Dict]):
        """Display enhanced analysis results"""
        print(f"\n📊 Top Opportunities (Enhanced Analysis)")
        print("-" * 60)
        
        if not opportunities:
            print("❌ No data available from any source")
            return
        
        for i, opp in enumerate(opportunities[:10], 1):
            quality_emoji = {
                'HIGH': '🟢',
                'MEDIUM': '🟡', 
                'LOW': '🔴'
            }.get(opp['data_quality'], '⚪')
            
            print(f"{i:2d}. {opp['symbol']:<6} | ${opp['price']:>8.2f} | "
                  f"{opp['change_percent']:>6.2f}% | Vol: {opp['volume']:>10,} | "
                  f"Score: {opp['score']:>3.0f} | {quality_emoji} {opp['data_source']}")
            
            if 'warning' in opp:
                print(f"     ⚠️  {opp['warning']}")
        
        print(f"\n🔍 Data Quality Legend:")
        print(f"   🟢 HIGH: Fresh, reliable data")
        print(f"   🟡 MEDIUM: Slightly delayed (< 1 hour)")
        print(f"   🔴 LOW: Stale data (> 1 hour old)")


def main():
    """Enhanced real-time analysis demo"""
    print("🚀 Enhanced Real-Time Stock Analysis")
    print("   Using Multiple Data Sources for Better Accuracy")
    print("=" * 65)
    
    # Popular stocks for testing
    test_symbols = ['AAPL', 'MSFT', 'SPY', 'QQQ', 'TSLA', 'NVDA', 'GOOGL', 'AMZN']
    
    # Initialize enhanced analyzer
    analyzer = EnhancedRealTimeAnalyzer()
    
    print(f"📋 Testing symbols: {', '.join(test_symbols)}")
    print(f"🕐 Analysis time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Run analysis
    opportunities = analyzer.analyze_opportunities(test_symbols)
    
    print(f"\n💡 Recommendations:")
    if opportunities:
        high_quality_opps = [opp for opp in opportunities if opp['data_quality'] == 'HIGH']
        
        if high_quality_opps:
            print(f"   ✅ {len(high_quality_opps)} opportunities with HIGH quality data")
            print(f"   🎯 Top pick: {high_quality_opps[0]['symbol']} (Score: {high_quality_opps[0]['score']:.0f})")
        else:
            print(f"   ⚠️  All data sources showing stale information")
            print(f"   💡 Consider getting Alpha Vantage API key for better data")
    else:
        print(f"   ❌ No data available from any source")


if __name__ == "__main__":
    main()