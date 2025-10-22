"""
Real-Time Market Analysis with Enhanced Data Precision
Demonstrates real-time capabilities for more accurate predictions
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os
import logging
import time
from typing import Dict, List

# Add src to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.data.enhanced_collector import EnhancedDataCollector
from src.prediction.stock_ranker import StockRanker
from src.analysis.technical_indicators import TechnicalAnalyzer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RealTimeAnalyzer:
    """Real-time market analyzer with enhanced data precision."""
    
    def __init__(self):
        """Initialize the real-time analyzer."""
        self.enhanced_collector = EnhancedDataCollector()
        self.technical_analyzer = TechnicalAnalyzer()
        
        # Real-time tracking
        self.last_analysis = {}
        self.price_alerts = {}
        self.trend_changes = {}
        
        logger.info("Real-time analyzer initialized")
    
    def analyze_real_time_opportunities(self, symbols: List[str]) -> Dict:
        """
        Analyze real-time trading opportunities.
        
        Args:
            symbols: List of stock symbols to analyze
            
        Returns:
            Dictionary with real-time analysis results
        """
        print("📊 REAL-TIME MARKET ANALYSIS")
        print("=" * 60)
        print(f"🕒 Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # Get precision analysis data
            precision_data = self.enhanced_collector.get_precision_analysis_data(symbols)
            
            # Get market context
            market_indicators = self.enhanced_collector.get_real_time_market_indicators()
            
            # Analyze each symbol
            analysis_results = {
                'timestamp': datetime.now(),
                'market_context': market_indicators,
                'individual_analysis': {},
                'opportunities': [],
                'alerts': [],
                'summary': {}
            }
            
            print(f"\n🌐 Market Context:")
            if '_summary' in market_indicators:
                summary = market_indicators['_summary']
                print(f"   Market Sentiment: {summary.get('sentiment_label', 'UNKNOWN')}")
                print(f"   Sentiment Score: {summary.get('market_sentiment_score', 0):.1f}%")
            
            print(f"\n📈 Individual Stock Analysis:")
            print("-" * 60)
            
            real_time_quotes = precision_data.get('real_time_quotes', {})
            
            for symbol in symbols:
                symbol_analysis = self._analyze_symbol_realtime(
                    symbol, 
                    real_time_quotes.get(symbol, {}),
                    precision_data.get('intraday_data', {}).get(symbol, {}),
                    market_indicators
                )
                
                analysis_results['individual_analysis'][symbol] = symbol_analysis
                
                # Display results
                self._display_symbol_analysis(symbol, symbol_analysis)
                
                # Check for opportunities and alerts
                if symbol_analysis.get('opportunity_score', 0) > 70:
                    analysis_results['opportunities'].append({
                        'symbol': symbol,
                        'score': symbol_analysis.get('opportunity_score', 0),
                        'reason': symbol_analysis.get('opportunity_reason', 'High potential detected')
                    })
                
                if symbol_analysis.get('alert_level', 'none') != 'none':
                    analysis_results['alerts'].append({
                        'symbol': symbol,
                        'alert': symbol_analysis.get('alert_level', 'none'),
                        'message': symbol_analysis.get('alert_message', 'Alert triggered')
                    })
            
            # Generate summary
            analysis_results['summary'] = self._generate_realtime_summary(analysis_results)
            
            # Display opportunities and alerts
            self._display_opportunities_alerts(analysis_results)
            
            return analysis_results
            
        except Exception as e:
            logger.error(f"Error in real-time analysis: {str(e)}")
            print(f"❌ Analysis failed: {str(e)}")
            return {}
    
    def _analyze_symbol_realtime(self, symbol: str, quote_data: Dict, 
                                intraday_data: Dict, market_context: Dict) -> Dict:
        """Analyze individual symbol in real-time."""
        try:
            analysis = {
                'symbol': symbol,
                'timestamp': datetime.now(),
                'current_price': quote_data.get('price', 0),
                'change_percent': quote_data.get('change_percent', 0),
                'volume_ratio': quote_data.get('volume_ratio', 1.0),
                'provider': quote_data.get('provider', 'unknown')
            }
            
            # Price momentum analysis
            change_pct = quote_data.get('change_percent', 0)
            if abs(change_pct) > 3:
                analysis['momentum'] = 'STRONG'
            elif abs(change_pct) > 1:
                analysis['momentum'] = 'MODERATE'
            else:
                analysis['momentum'] = 'WEAK'
            
            # Volume analysis
            volume_ratio = quote_data.get('volume_ratio', 1.0)
            if volume_ratio > 2:
                analysis['volume_signal'] = 'HIGH_VOLUME'
            elif volume_ratio > 1.5:
                analysis['volume_signal'] = 'ELEVATED_VOLUME'
            else:
                analysis['volume_signal'] = 'NORMAL_VOLUME'
            
            # Intraday trend analysis
            if intraday_data:
                price_trend = intraday_data.get('price_trend', 0)
                volume_trend = intraday_data.get('volume_trend', 0)
                volatility = intraday_data.get('volatility', 0)
                
                analysis['intraday_trend'] = price_trend
                analysis['volume_trend'] = volume_trend
                analysis['volatility'] = volatility
                
                # Trend strength
                if abs(price_trend) > 2:
                    analysis['trend_strength'] = 'STRONG'
                elif abs(price_trend) > 0.5:
                    analysis['trend_strength'] = 'MODERATE'
                else:
                    analysis['trend_strength'] = 'WEAK'
            
            # Market correlation
            if '_summary' in market_context:
                market_sentiment = market_context['_summary'].get('market_sentiment_score', 50)
                stock_positive = change_pct > 0
                market_positive = market_sentiment > 50
                
                if stock_positive == market_positive:
                    analysis['market_correlation'] = 'ALIGNED'
                else:
                    analysis['market_correlation'] = 'DIVERGENT'
            
            # Calculate opportunity score
            opportunity_score = self._calculate_opportunity_score(analysis)
            analysis['opportunity_score'] = opportunity_score
            
            # Generate trading signals
            signals = self._generate_trading_signals(analysis)
            analysis['signals'] = signals
            
            # Alert conditions
            alert_level, alert_message = self._check_alert_conditions(analysis)
            analysis['alert_level'] = alert_level
            analysis['alert_message'] = alert_message
            
            # Opportunity reason
            if opportunity_score > 70:
                analysis['opportunity_reason'] = self._get_opportunity_reason(analysis)
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {str(e)}")
            return {'symbol': symbol, 'error': str(e)}
    
    def _calculate_opportunity_score(self, analysis: Dict) -> float:
        """Calculate opportunity score based on multiple factors."""
        score = 50  # Base score
        
        # Price momentum factor
        change_pct = analysis.get('change_percent', 0)
        if change_pct > 2:
            score += 20
        elif change_pct > 1:
            score += 10
        elif change_pct > 0:
            score += 5
        
        # Volume factor
        volume_signal = analysis.get('volume_signal', 'NORMAL_VOLUME')
        if volume_signal == 'HIGH_VOLUME':
            score += 15
        elif volume_signal == 'ELEVATED_VOLUME':
            score += 10
        
        # Momentum factor
        momentum = analysis.get('momentum', 'WEAK')
        if momentum == 'STRONG':
            score += 15
        elif momentum == 'MODERATE':
            score += 8
        
        # Trend factor
        trend_strength = analysis.get('trend_strength', 'WEAK')
        if trend_strength == 'STRONG':
            score += 10
        elif trend_strength == 'MODERATE':
            score += 5
        
        # Market correlation factor
        correlation = analysis.get('market_correlation', 'ALIGNED')
        if correlation == 'ALIGNED':
            score += 5
        
        return min(100, max(0, score))
    
    def _generate_trading_signals(self, analysis: Dict) -> List[str]:
        """Generate trading signals based on analysis."""
        signals = []
        
        change_pct = analysis.get('change_percent', 0)
        momentum = analysis.get('momentum', 'WEAK')
        volume_signal = analysis.get('volume_signal', 'NORMAL_VOLUME')
        opportunity_score = analysis.get('opportunity_score', 0)
        
        # Price signals
        if change_pct > 3:
            signals.append("🚀 STRONG_UPWARD_MOVE")
        elif change_pct > 1:
            signals.append("📈 POSITIVE_MOMENTUM")
        elif change_pct < -3:
            signals.append("📉 STRONG_DOWNWARD_MOVE")
        elif change_pct < -1:
            signals.append("⬇️ NEGATIVE_MOMENTUM")
        
        # Volume signals
        if volume_signal == 'HIGH_VOLUME':
            signals.append("🔊 HIGH_VOLUME_ACTIVITY")
        elif volume_signal == 'ELEVATED_VOLUME':
            signals.append("📊 ELEVATED_VOLUME")
        
        # Opportunity signals
        if opportunity_score > 80:
            signals.append("⭐ STRONG_BUY_SIGNAL")
        elif opportunity_score > 70:
            signals.append("✅ BUY_SIGNAL")
        elif opportunity_score < 30:
            signals.append("🔴 AVOID_SIGNAL")
        
        # Trend signals
        trend_strength = analysis.get('trend_strength', 'WEAK')
        if trend_strength == 'STRONG':
            signals.append("📊 STRONG_TREND_CONTINUATION")
        
        return signals
    
    def _check_alert_conditions(self, analysis: Dict) -> tuple:
        """Check for alert conditions."""
        change_pct = analysis.get('change_percent', 0)
        volume_ratio = analysis.get('volume_ratio', 1.0)
        volatility = analysis.get('volatility', 0)
        
        # High priority alerts
        if abs(change_pct) > 5:
            return 'HIGH', f"Extreme price movement: {change_pct:+.2f}%"
        
        if volume_ratio > 3:
            return 'HIGH', f"Unusual volume: {volume_ratio:.1f}x normal"
        
        if volatility > 5:
            return 'HIGH', f"High volatility detected: {volatility:.2f}%"
        
        # Medium priority alerts
        if abs(change_pct) > 3:
            return 'MEDIUM', f"Significant price movement: {change_pct:+.2f}%"
        
        if volume_ratio > 2:
            return 'MEDIUM', f"Elevated volume: {volume_ratio:.1f}x normal"
        
        return 'none', ''
    
    def _get_opportunity_reason(self, analysis: Dict) -> str:
        """Get reason for high opportunity score."""
        reasons = []
        
        if analysis.get('momentum') == 'STRONG':
            reasons.append("strong price momentum")
        
        if analysis.get('volume_signal') == 'HIGH_VOLUME':
            reasons.append("high volume confirmation")
        
        if analysis.get('trend_strength') == 'STRONG':
            reasons.append("strong intraday trend")
        
        if analysis.get('market_correlation') == 'ALIGNED':
            reasons.append("aligned with market")
        
        return ", ".join(reasons) if reasons else "multiple positive factors"
    
    def _display_symbol_analysis(self, symbol: str, analysis: Dict):
        """Display analysis results for a symbol."""
        if 'error' in analysis:
            print(f"❌ {symbol}: Error - {analysis['error']}")
            return
        
        price = analysis.get('current_price', 0)
        change_pct = analysis.get('change_percent', 0)
        opportunity_score = analysis.get('opportunity_score', 0)
        momentum = analysis.get('momentum', 'UNKNOWN')
        volume_signal = analysis.get('volume_signal', 'UNKNOWN')
        
        # Color coding
        price_emoji = "🟢" if change_pct > 0 else "🔴" if change_pct < 0 else "⚪"
        score_emoji = "⭐" if opportunity_score > 80 else "✅" if opportunity_score > 70 else "⚠️" if opportunity_score > 50 else "🔴"
        
        print(f"{price_emoji} {symbol:<6} | ${price:<8.2f} | {change_pct:+6.2f}% | "
              f"{score_emoji} Score: {opportunity_score:3.0f} | {momentum:<8} | {volume_signal}")
        
        # Show key signals
        signals = analysis.get('signals', [])
        if signals:
            key_signals = signals[:2]  # Show top 2 signals
            print(f"          Signals: {', '.join(key_signals)}")
    
    def _generate_realtime_summary(self, results: Dict) -> Dict:
        """Generate summary of real-time analysis."""
        individual_analyses = results.get('individual_analysis', {})
        
        if not individual_analyses:
            return {}
        
        # Calculate summary statistics
        prices = [a.get('current_price', 0) for a in individual_analyses.values()]
        changes = [a.get('change_percent', 0) for a in individual_analyses.values()]
        scores = [a.get('opportunity_score', 0) for a in individual_analyses.values()]
        
        positive_movers = len([c for c in changes if c > 0])
        negative_movers = len([c for c in changes if c < 0])
        high_opportunity = len([s for s in scores if s > 70])
        
        return {
            'total_analyzed': len(individual_analyses),
            'positive_movers': positive_movers,
            'negative_movers': negative_movers,
            'avg_change_percent': np.mean(changes),
            'avg_opportunity_score': np.mean(scores),
            'high_opportunity_count': high_opportunity,
            'market_bias': 'BULLISH' if positive_movers > negative_movers else 'BEARISH' if negative_movers > positive_movers else 'NEUTRAL'
        }
    
    def _display_opportunities_alerts(self, results: Dict):
        """Display opportunities and alerts."""
        opportunities = results.get('opportunities', [])
        alerts = results.get('alerts', [])
        summary = results.get('summary', {})
        
        print(f"\n🎯 REAL-TIME OPPORTUNITIES")
        print("-" * 40)
        
        if opportunities:
            for opp in opportunities:
                print(f"⭐ {opp['symbol']}: Score {opp['score']:.0f} - {opp['reason']}")
        else:
            print("   No high-probability opportunities detected")
        
        print(f"\n🚨 ACTIVE ALERTS")
        print("-" * 40)
        
        if alerts:
            for alert in alerts:
                alert_emoji = "🔥" if alert['alert'] == 'HIGH' else "⚠️"
                print(f"{alert_emoji} {alert['symbol']}: {alert['message']}")
        else:
            print("   No active alerts")
        
        print(f"\n📊 REAL-TIME SUMMARY")
        print("-" * 40)
        
        if summary:
            print(f"Market Bias: {summary.get('market_bias', 'UNKNOWN')}")
            print(f"Positive Movers: {summary.get('positive_movers', 0)}/{summary.get('total_analyzed', 0)}")
            print(f"High Opportunities: {summary.get('high_opportunity_count', 0)}")
            print(f"Avg Change: {summary.get('avg_change_percent', 0):+.2f}%")
            print(f"Avg Opportunity Score: {summary.get('avg_opportunity_score', 0):.1f}")
    
    def run_continuous_monitoring(self, symbols: List[str], interval_minutes: int = 5):
        """
        Run continuous real-time monitoring.
        
        Args:
            symbols: Symbols to monitor
            interval_minutes: Update interval in minutes
        """
        print(f"🔄 Starting continuous monitoring for {len(symbols)} symbols")
        print(f"⏰ Update interval: {interval_minutes} minutes")
        print("Press Ctrl+C to stop...")
        print()
        
        try:
            while True:
                # Run analysis
                results = self.analyze_real_time_opportunities(symbols)
                
                # Save results
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_file = f"data/realtime_analysis_{timestamp}.json"
                
                import json
                with open(output_file, 'w') as f:
                    # Convert datetime objects to strings for JSON serialization
                    json_results = self._serialize_for_json(results)
                    json.dump(json_results, f, indent=2)
                
                print(f"\n💾 Results saved to: {output_file}")
                print(f"⏰ Next update in {interval_minutes} minutes...")
                print("=" * 60)
                
                # Wait for next interval
                time.sleep(interval_minutes * 60)
                
        except KeyboardInterrupt:
            print("\n🛑 Monitoring stopped by user")
        except Exception as e:
            logger.error(f"Error in continuous monitoring: {str(e)}")
            print(f"❌ Monitoring error: {str(e)}")
    
    def _serialize_for_json(self, obj):
        """Convert datetime objects to strings for JSON serialization."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {key: self._serialize_for_json(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize_for_json(item) for item in obj]
        else:
            return obj


def main():
    """Main function to run real-time analysis."""
    print("🚀 REAL-TIME MARKET ANALYZER")
    print("=" * 50)
    
    # Default symbols for analysis
    symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM', 'V', 'UNH']
    
    analyzer = RealTimeAnalyzer()
    
    print("\nSelect analysis mode:")
    print("1. Single real-time analysis")
    print("2. Continuous monitoring")
    print("3. Custom symbol list")
    
    try:
        choice = input("\nEnter choice (1-3, default 1): ").strip() or "1"
        
        if choice == "3":
            custom_symbols = input("Enter symbols (comma-separated): ").strip()
            if custom_symbols:
                symbols = [s.strip().upper() for s in custom_symbols.split(',')]
        
        if choice == "2":
            interval = input("Enter monitoring interval in minutes (default 5): ").strip()
            interval_minutes = int(interval) if interval.isdigit() else 5
            analyzer.run_continuous_monitoring(symbols, interval_minutes)
        else:
            # Single analysis
            results = analyzer.analyze_real_time_opportunities(symbols)
            
            if results:
                print("\n✅ Real-time analysis completed successfully!")
            else:
                print("\n❌ Analysis failed")
    
    except KeyboardInterrupt:
        print("\n👋 Analysis stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")


if __name__ == "__main__":
    main()