"""
Professional Stock Market Prediction System
Using High-Quality Alpha Vantage Real-Time Data
"""

import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Dict, List, Tuple
from dotenv import load_dotenv

load_dotenv()

class ProfessionalStockPredictor:
    """
    Advanced stock prediction system using high-quality real-time data
    """
    
    def __init__(self):
        self.api_key = os.getenv('ALPHA_VANTAGE_API_KEY')
        self.base_url = "https://www.alphavantage.co/query"
        self.cache = {}
        self.last_request_time = {}
        
        print(f"🔑 Professional Predictor initialized with API key: {self.api_key[:8]}***")
    
    def _rate_limit(self, delay: float = 12):
        """Respect API rate limits (5 requests per minute)"""
        now = time.time()
        if hasattr(self, '_last_request') and (now - self._last_request) < delay:
            sleep_time = delay - (now - self._last_request)
            time.sleep(sleep_time)
        self._last_request = now
    
    def get_intraday_data(self, symbol: str, interval: str = '5min') -> pd.DataFrame:
        """Get high-quality intraday data for technical analysis"""
        self._rate_limit()
        
        params = {
            'function': 'TIME_SERIES_INTRADAY',
            'symbol': symbol,
            'interval': interval,
            'apikey': self.api_key,
            'outputsize': 'full'  # Get more data for better analysis
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
                
                print(f"✅ {symbol}: Got {len(df)} data points from {df.index[0]} to {df.index[-1]}")
                return df
            else:
                print(f"⚠️ {symbol}: API response issue - {data.get('Information', 'Unknown error')}")
                return pd.DataFrame()
                
        except Exception as e:
            print(f"❌ {symbol}: Error getting intraday data - {e}")
            return pd.DataFrame()
    
    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate professional technical indicators"""
        if df.empty:
            return df
        
        # Moving averages
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
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
        
        # Price momentum
        df['Price_Change_1h'] = df['Close'].pct_change(periods=12)  # 12 * 5min = 1 hour
        df['Price_Change_30m'] = df['Close'].pct_change(periods=6)   # 6 * 5min = 30 min
        
        return df
    
    def generate_prediction_signals(self, df: pd.DataFrame, symbol: str) -> Dict:
        """Generate professional prediction signals"""
        if df.empty or len(df) < 50:
            return {'symbol': symbol, 'signal': 'INSUFFICIENT_DATA', 'confidence': 0}
        
        latest = df.iloc[-1]
        signals = []
        reasons = []
        
        # MACD Signal
        if latest['MACD'] > latest['MACD_Signal'] and latest['MACD_Histogram'] > 0:
            signals.append(1)
            reasons.append("MACD bullish crossover")
        elif latest['MACD'] < latest['MACD_Signal'] and latest['MACD_Histogram'] < 0:
            signals.append(-1)
            reasons.append("MACD bearish crossover")
        
        # RSI Signal
        if latest['RSI'] < 30:  # Oversold
            signals.append(1)
            reasons.append("RSI oversold (potential bounce)")
        elif latest['RSI'] > 70:  # Overbought
            signals.append(-1)
            reasons.append("RSI overbought (potential pullback)")
        
        # Bollinger Bands Signal
        if latest['BB_Position'] < 0.1:  # Near lower band
            signals.append(1)
            reasons.append("Near lower Bollinger Band")
        elif latest['BB_Position'] > 0.9:  # Near upper band
            signals.append(-1)
            reasons.append("Near upper Bollinger Band")
        
        # Moving Average Signal
        if latest['Close'] > latest['SMA_20'] > latest['SMA_50']:
            signals.append(1)
            reasons.append("Price above rising moving averages")
        elif latest['Close'] < latest['SMA_20'] < latest['SMA_50']:
            signals.append(-1)
            reasons.append("Price below falling moving averages")
        
        # Volume Confirmation
        if latest['Volume_Ratio'] > 1.5:  # High volume
            if signals and signals[-1] == 1:
                reasons.append("High volume confirms bullish signal")
            elif signals and signals[-1] == -1:
                reasons.append("High volume confirms bearish signal")
        
        # Price Momentum
        if latest['Price_Change_30m'] > 0.02:  # Strong 30-min momentum
            signals.append(1)
            reasons.append("Strong upward momentum (30min)")
        elif latest['Price_Change_30m'] < -0.02:
            signals.append(-1)
            reasons.append("Strong downward momentum (30min)")
        
        # Calculate overall signal
        if not signals:
            overall_signal = 'NEUTRAL'
            confidence = 50
        else:
            signal_sum = sum(signals)
            signal_count = len(signals)
            
            if signal_sum > 0:
                overall_signal = 'BUY'
                confidence = min(95, 60 + (signal_sum / signal_count) * 35)
            elif signal_sum < 0:
                overall_signal = 'SELL'
                confidence = min(95, 60 + abs(signal_sum / signal_count) * 35)
            else:
                overall_signal = 'NEUTRAL'
                confidence = 50
        
        return {
            'symbol': symbol,
            'signal': overall_signal,
            'confidence': round(confidence, 1),
            'price': latest['Close'],
            'volume': latest['Volume'],
            'rsi': round(latest['RSI'], 1),
            'bb_position': round(latest['BB_Position'], 2),
            'volume_ratio': round(latest['Volume_Ratio'], 1),
            'price_change_30m': round(latest['Price_Change_30m'] * 100, 2),
            'reasons': reasons,
            'timestamp': datetime.now()
        }
    
    def analyze_portfolio(self, symbols: List[str]) -> List[Dict]:
        """Analyze a portfolio of stocks with professional predictions"""
        print(f"🔬 Professional Stock Analysis - {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 70)
        
        predictions = []
        
        for i, symbol in enumerate(symbols, 1):
            print(f"📊 Analyzing {symbol} ({i}/{len(symbols)})...")
            
            # Get high-quality intraday data
            df = self.get_intraday_data(symbol, '5min')
            
            if not df.empty:
                # Calculate technical indicators
                df = self.calculate_technical_indicators(df)
                
                # Generate prediction
                prediction = self.generate_prediction_signals(df, symbol)
                predictions.append(prediction)
            else:
                print(f"⚠️ {symbol}: No data available")
        
        # Sort by confidence (highest first)
        predictions.sort(key=lambda x: x['confidence'], reverse=True)
        
        return predictions
    
    def display_predictions(self, predictions: List[Dict]):
        """Display professional prediction results"""
        print(f"\n🎯 Professional Stock Predictions")
        print("=" * 70)
        
        if not predictions:
            print("❌ No predictions available")
            return
        
        # Summary statistics
        buy_signals = len([p for p in predictions if p['signal'] == 'BUY'])
        sell_signals = len([p for p in predictions if p['signal'] == 'SELL'])
        neutral_signals = len([p for p in predictions if p['signal'] == 'NEUTRAL'])
        
        print(f"📈 Market Sentiment: {buy_signals} BUY | {sell_signals} SELL | {neutral_signals} NEUTRAL")
        print("-" * 70)
        
        for i, pred in enumerate(predictions, 1):
            signal_emoji = {'BUY': '🟢', 'SELL': '🔴', 'NEUTRAL': '🟡'}.get(pred['signal'], '⚪')
            confidence_bar = "█" * int(pred['confidence'] / 10)
            
            print(f"{i:2d}. {pred['symbol']:<6} | {signal_emoji} {pred['signal']:<7} | "
                  f"Conf: {pred['confidence']:>5.1f}% {confidence_bar:<10} | "
                  f"${pred['price']:>8.2f} | RSI: {pred['rsi']:>5.1f}")
            
            if pred['reasons']:
                print(f"     💡 {', '.join(pred['reasons'][:2])}")  # Show top 2 reasons
        
        print(f"\n🏆 Top Recommendations:")
        top_buys = [p for p in predictions if p['signal'] == 'BUY'][:3]
        
        if top_buys:
            for i, pred in enumerate(top_buys, 1):
                print(f"   {i}. {pred['symbol']}: {pred['signal']} ({pred['confidence']:.1f}% confidence)")
        else:
            print("   No strong BUY signals detected")


def main():
    """Professional stock prediction demo"""
    print("🚀 Professional Stock Market Prediction System")
    print("   Powered by Alpha Vantage High-Quality Real-Time Data")
    print("=" * 65)
    
    # Popular stocks for analysis
    portfolio = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA']
    
    # Initialize predictor
    predictor = ProfessionalStockPredictor()
    
    print(f"📋 Analyzing portfolio: {', '.join(portfolio)}")
    print(f"🕐 Analysis time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Run professional analysis
    predictions = predictor.analyze_portfolio(portfolio)
    
    # Display results
    predictor.display_predictions(predictions)
    
    print(f"\n💼 Analysis Complete!")
    print(f"   📊 {len(predictions)} stocks analyzed")
    print(f"   🎯 Using professional-grade Alpha Vantage data")
    print(f"   ⚡ Real-time technical analysis with multiple indicators")


if __name__ == "__main__":
    main()