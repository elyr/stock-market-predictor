"""
Technical analysis module with various indicators and pattern recognition.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
import logging
from scipy.signal import argrelextrema
import talib
import warnings

# Suppress warnings for cleaner output
warnings.filterwarnings('ignore')

logger = logging.getLogger(__name__)


class TechnicalAnalyzer:
    """
    Comprehensive technical analysis class with various indicators and patterns.
    """
    
    def __init__(self, config: Dict = None):
        """Initialize with configuration parameters."""
        self.config = config or self._default_config()
    
    def _default_config(self) -> Dict:
        """Default configuration for technical indicators."""
        return {
            'rsi': {'period': 14, 'overbought': 70, 'oversold': 30},
            'macd': {'fast_period': 12, 'slow_period': 26, 'signal_period': 9},
            'bollinger_bands': {'period': 20, 'std_dev': 2},
            'stochastic': {'k_period': 14, 'd_period': 3},
            'atr': {'period': 14},
            'adx': {'period': 14},
            'cci': {'period': 20}
        }
    
    def calculate_rsi(self, data: pd.DataFrame, period: int = None) -> pd.Series:
        """
        Calculate Relative Strength Index (RSI).
        
        Args:
            data: DataFrame with 'Close' column
            period: RSI period (default from config)
        
        Returns:
            RSI values as pandas Series
        """
        if period is None:
            period = self.config['rsi']['period']
        
        close_prices = data['Close']
        
        # Calculate price changes
        delta = close_prices.diff()
        
        # Separate gains and losses
        gains = delta.where(delta > 0, 0)
        losses = -delta.where(delta < 0, 0)
        
        # Calculate average gains and losses
        avg_gains = gains.ewm(span=period).mean()
        avg_losses = losses.ewm(span=period).mean()
        
        # Calculate RSI
        rs = avg_gains / avg_losses
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calculate_macd(self, data: pd.DataFrame, fast_period: int = None, 
                      slow_period: int = None, signal_period: int = None) -> Dict[str, pd.Series]:
        """
        Calculate MACD (Moving Average Convergence Divergence).
        
        Args:
            data: DataFrame with 'Close' column
            fast_period: Fast EMA period
            slow_period: Slow EMA period
            signal_period: Signal line EMA period
        
        Returns:
            Dictionary with MACD line, signal line, and histogram
        """
        if fast_period is None:
            fast_period = self.config['macd']['fast_period']
        if slow_period is None:
            slow_period = self.config['macd']['slow_period']
        if signal_period is None:
            signal_period = self.config['macd']['signal_period']
        
        close_prices = data['Close']
        
        # Calculate EMAs
        ema_fast = close_prices.ewm(span=fast_period).mean()
        ema_slow = close_prices.ewm(span=slow_period).mean()
        
        # Calculate MACD line
        macd_line = ema_fast - ema_slow
        
        # Calculate signal line
        signal_line = macd_line.ewm(span=signal_period).mean()
        
        # Calculate histogram
        histogram = macd_line - signal_line
        
        return {
            'MACD': macd_line,
            'MACD_Signal': signal_line,
            'MACD_Histogram': histogram
        }
    
    def calculate_bollinger_bands(self, data: pd.DataFrame, period: int = None, 
                                 std_dev: float = None) -> Dict[str, pd.Series]:
        """
        Calculate Bollinger Bands.
        
        Args:
            data: DataFrame with 'Close' column
            period: Moving average period
            std_dev: Standard deviation multiplier
        
        Returns:
            Dictionary with upper, middle, and lower bands
        """
        if period is None:
            period = self.config['bollinger_bands']['period']
        if std_dev is None:
            std_dev = self.config['bollinger_bands']['std_dev']
        
        close_prices = data['Close']
        
        # Calculate middle band (SMA)
        middle_band = close_prices.rolling(window=period).mean()
        
        # Calculate standard deviation
        std = close_prices.rolling(window=period).std()
        
        # Calculate upper and lower bands
        upper_band = middle_band + (std * std_dev)
        lower_band = middle_band - (std * std_dev)
        
        return {
            'BB_Upper': upper_band,
            'BB_Middle': middle_band,
            'BB_Lower': lower_band,
            'BB_Width': upper_band - lower_band,
            'BB_Position': (close_prices - lower_band) / (upper_band - lower_band)
        }
    
    def calculate_stochastic(self, data: pd.DataFrame, k_period: int = None, 
                           d_period: int = None) -> Dict[str, pd.Series]:
        """
        Calculate Stochastic Oscillator.
        
        Args:
            data: DataFrame with 'High', 'Low', 'Close' columns
            k_period: %K period
            d_period: %D period
        
        Returns:
            Dictionary with %K and %D values
        """
        if k_period is None:
            k_period = self.config['stochastic']['k_period']
        if d_period is None:
            d_period = self.config['stochastic']['d_period']
        
        high_prices = data['High']
        low_prices = data['Low']
        close_prices = data['Close']
        
        # Calculate %K
        lowest_low = low_prices.rolling(window=k_period).min()
        highest_high = high_prices.rolling(window=k_period).max()
        
        k_percent = 100 * ((close_prices - lowest_low) / (highest_high - lowest_low))
        
        # Calculate %D (smoothed %K)
        d_percent = k_percent.rolling(window=d_period).mean()
        
        return {
            'Stoch_K': k_percent,
            'Stoch_D': d_percent
        }
    
    def calculate_atr(self, data: pd.DataFrame, period: int = None) -> pd.Series:
        """
        Calculate Average True Range (ATR).
        
        Args:
            data: DataFrame with 'High', 'Low', 'Close' columns
            period: ATR period
        
        Returns:
            ATR values as pandas Series
        """
        if period is None:
            period = self.config['atr']['period']
        
        high_prices = data['High']
        low_prices = data['Low']
        close_prices = data['Close']
        
        # Calculate True Range
        tr1 = high_prices - low_prices
        tr2 = abs(high_prices - close_prices.shift(1))
        tr3 = abs(low_prices - close_prices.shift(1))
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Calculate ATR
        atr = true_range.ewm(span=period).mean()
        
        return atr
    
    def calculate_adx(self, data: pd.DataFrame, period: int = None) -> Dict[str, pd.Series]:
        """
        Calculate Average Directional Index (ADX) and Directional Indicators.
        
        Args:
            data: DataFrame with 'High', 'Low', 'Close' columns
            period: ADX period
        
        Returns:
            Dictionary with ADX, +DI, and -DI values
        """
        if period is None:
            period = self.config['adx']['period']
        
        high_prices = data['High']
        low_prices = data['Low']
        close_prices = data['Close']
        
        # Calculate True Range
        tr = self.calculate_atr(data, period=1)  # Single period TR
        
        # Calculate Directional Movement
        dm_plus = high_prices.diff()
        dm_minus = -low_prices.diff()
        
        dm_plus[dm_plus < 0] = 0
        dm_minus[dm_minus < 0] = 0
        
        # Smooth DM and TR
        dm_plus_smooth = dm_plus.ewm(span=period).mean()
        dm_minus_smooth = dm_minus.ewm(span=period).mean()
        tr_smooth = tr.ewm(span=period).mean()
        
        # Calculate Directional Indicators
        di_plus = 100 * (dm_plus_smooth / tr_smooth)
        di_minus = 100 * (dm_minus_smooth / tr_smooth)
        
        # Calculate DX and ADX
        dx = 100 * abs(di_plus - di_minus) / (di_plus + di_minus)
        adx = dx.ewm(span=period).mean()
        
        return {
            'ADX': adx,
            'DI_Plus': di_plus,
            'DI_Minus': di_minus
        }
    
    def calculate_cci(self, data: pd.DataFrame, period: int = None) -> pd.Series:
        """
        Calculate Commodity Channel Index (CCI).
        
        Args:
            data: DataFrame with 'High', 'Low', 'Close' columns
            period: CCI period
        
        Returns:
            CCI values as pandas Series
        """
        if period is None:
            period = self.config['cci']['period']
        
        # Calculate Typical Price
        typical_price = (data['High'] + data['Low'] + data['Close']) / 3
        
        # Calculate SMA of Typical Price
        sma_tp = typical_price.rolling(window=period).mean()
        
        # Calculate Mean Absolute Deviation
        mad = typical_price.rolling(window=period).apply(
            lambda x: np.mean(np.abs(x - x.mean()))
        )
        
        # Calculate CCI
        cci = (typical_price - sma_tp) / (0.015 * mad)
        
        return cci
    
    def calculate_obv(self, data: pd.DataFrame) -> pd.Series:
        """
        Calculate On-Balance Volume (OBV).
        
        Args:
            data: DataFrame with 'Close' and 'Volume' columns
        
        Returns:
            OBV values as pandas Series
        """
        close_prices = data['Close']
        volume = data['Volume']
        
        # Calculate price direction
        price_direction = np.sign(close_prices.diff())
        
        # Calculate OBV
        obv = (price_direction * volume).cumsum()
        
        return obv
    
    def calculate_money_flow_index(self, data: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Calculate Money Flow Index (MFI).
        
        Args:
            data: DataFrame with OHLCV data
            period: MFI period
        
        Returns:
            MFI values as pandas Series
        """
        # Calculate Typical Price
        typical_price = (data['High'] + data['Low'] + data['Close']) / 3
        
        # Calculate Raw Money Flow
        money_flow = typical_price * data['Volume']
        
        # Separate positive and negative money flows
        price_change = typical_price.diff()
        positive_flow = money_flow.where(price_change > 0, 0)
        negative_flow = money_flow.where(price_change < 0, 0)
        
        # Calculate Money Flow Ratio
        positive_flow_sum = positive_flow.rolling(window=period).sum()
        negative_flow_sum = negative_flow.rolling(window=period).sum()
        
        money_flow_ratio = positive_flow_sum / negative_flow_sum
        
        # Calculate MFI
        mfi = 100 - (100 / (1 + money_flow_ratio))
        
        return mfi
    
    def find_support_resistance(self, data: pd.DataFrame, window: int = 20, 
                               min_touches: int = 2) -> Dict[str, List[float]]:
        """
        Find support and resistance levels using pivot points.
        
        Args:
            data: DataFrame with OHLC data
            window: Window for finding local extrema
            min_touches: Minimum number of touches to confirm S/R level
        
        Returns:
            Dictionary with support and resistance levels
        """
        high_prices = data['High'].values
        low_prices = data['Low'].values
        
        # Find local maxima (resistance) and minima (support)
        resistance_indices = argrelextrema(high_prices, np.greater, order=window)[0]
        support_indices = argrelextrema(low_prices, np.less, order=window)[0]
        
        resistance_levels = high_prices[resistance_indices]
        support_levels = low_prices[support_indices]
        
        # Group similar levels together (within 1% of each other)
        def group_levels(levels, tolerance=0.01):
            if len(levels) == 0:
                return []
            
            grouped_levels = []
            sorted_levels = np.sort(levels)
            
            current_group = [sorted_levels[0]]
            
            for level in sorted_levels[1:]:
                if abs(level - current_group[-1]) / current_group[-1] <= tolerance:
                    current_group.append(level)
                else:
                    if len(current_group) >= min_touches:
                        grouped_levels.append(np.mean(current_group))
                    current_group = [level]
            
            if len(current_group) >= min_touches:
                grouped_levels.append(np.mean(current_group))
            
            return grouped_levels
        
        return {
            'resistance': group_levels(resistance_levels),
            'support': group_levels(support_levels)
        }
    
    def detect_chart_patterns(self, data: pd.DataFrame) -> Dict[str, bool]:
        """
        Detect various chart patterns.
        
        Args:
            data: DataFrame with OHLC data
        
        Returns:
            Dictionary indicating presence of patterns
        """
        patterns = {}
        
        # Get recent data (last 20 periods)
        recent_data = data.tail(20).copy()
        
        if len(recent_data) < 10:
            return patterns
        
        high_prices = recent_data['High'].values
        low_prices = recent_data['Low'].values
        close_prices = recent_data['Close'].values
        
        # Double Top Pattern
        peaks = argrelextrema(high_prices, np.greater, order=3)[0]
        if len(peaks) >= 2:
            last_two_peaks = peaks[-2:]
            peak_diff = abs(high_prices[last_two_peaks[0]] - high_prices[last_two_peaks[1]])
            avg_peak = np.mean(high_prices[last_two_peaks])
            patterns['double_top'] = (peak_diff / avg_peak) < 0.02  # Within 2%
        else:
            patterns['double_top'] = False
        
        # Double Bottom Pattern
        troughs = argrelextrema(low_prices, np.less, order=3)[0]
        if len(troughs) >= 2:
            last_two_troughs = troughs[-2:]
            trough_diff = abs(low_prices[last_two_troughs[0]] - low_prices[last_two_troughs[1]])
            avg_trough = np.mean(low_prices[last_two_troughs])
            patterns['double_bottom'] = (trough_diff / avg_trough) < 0.02  # Within 2%
        else:
            patterns['double_bottom'] = False
        
        # Head and Shoulders Pattern (simplified)
        if len(peaks) >= 3:
            last_three_peaks = peaks[-3:]
            left_shoulder = high_prices[last_three_peaks[0]]
            head = high_prices[last_three_peaks[1]]
            right_shoulder = high_prices[last_three_peaks[2]]
            
            # Head should be higher than shoulders, shoulders should be similar
            patterns['head_and_shoulders'] = (
                head > left_shoulder and 
                head > right_shoulder and
                abs(left_shoulder - right_shoulder) / np.mean([left_shoulder, right_shoulder]) < 0.05
            )
        else:
            patterns['head_and_shoulders'] = False
        
        # Ascending Triangle
        if len(peaks) >= 2 and len(troughs) >= 2:
            recent_peaks = high_prices[peaks[-2:]]
            recent_troughs = low_prices[troughs[-2:]]
            
            # Resistance line should be flat, support line should be ascending
            resistance_flat = abs(recent_peaks[1] - recent_peaks[0]) / recent_peaks[0] < 0.02
            support_ascending = recent_troughs[1] > recent_troughs[0]
            
            patterns['ascending_triangle'] = resistance_flat and support_ascending
        else:
            patterns['ascending_triangle'] = False
        
        # Descending Triangle
        if len(peaks) >= 2 and len(troughs) >= 2:
            recent_peaks = high_prices[peaks[-2:]]
            recent_troughs = low_prices[troughs[-2:]]
            
            # Support line should be flat, resistance line should be descending
            support_flat = abs(recent_troughs[1] - recent_troughs[0]) / recent_troughs[0] < 0.02
            resistance_descending = recent_peaks[1] < recent_peaks[0]
            
            patterns['descending_triangle'] = support_flat and resistance_descending
        else:
            patterns['descending_triangle'] = False
        
        # Bullish Flag
        # Look for a strong upward move followed by a slight downward consolidation
        if len(close_prices) >= 10:
            recent_trend = np.polyfit(range(len(close_prices)), close_prices, 1)[0]
            mid_point = len(close_prices) // 2
            
            early_trend = np.polyfit(range(mid_point), close_prices[:mid_point], 1)[0]
            late_trend = np.polyfit(range(mid_point), close_prices[mid_point:], 1)[0]
            
            patterns['bullish_flag'] = early_trend > 0.02 and -0.01 < late_trend < 0.01
        else:
            patterns['bullish_flag'] = False
        
        return patterns
    
    def calculate_all_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all technical indicators and add them to the DataFrame.
        
        Args:
            data: DataFrame with OHLCV data
        
        Returns:
            DataFrame with all technical indicators
        """
        df = data.copy()
        
        try:
            # Trend Indicators
            df['RSI'] = self.calculate_rsi(df)
            
            macd_dict = self.calculate_macd(df)
            for key, value in macd_dict.items():
                df[key] = value
            
            bb_dict = self.calculate_bollinger_bands(df)
            for key, value in bb_dict.items():
                df[key] = value
            
            # Momentum Indicators
            stoch_dict = self.calculate_stochastic(df)
            for key, value in stoch_dict.items():
                df[key] = value
            
            df['CCI'] = self.calculate_cci(df)
            df['MFI'] = self.calculate_money_flow_index(df)
            
            # Volatility Indicators
            df['ATR'] = self.calculate_atr(df)
            
            # Volume Indicators
            df['OBV'] = self.calculate_obv(df)
            
            # Trend Strength
            adx_dict = self.calculate_adx(df)
            for key, value in adx_dict.items():
                df[key] = value
            
            # Support/Resistance and Patterns
            sr_levels = self.find_support_resistance(df)
            patterns = self.detect_chart_patterns(df)
            
            # Add pattern detection as binary features
            for pattern, detected in patterns.items():
                df[f'Pattern_{pattern}'] = detected
            
            # Add signal interpretation
            df = self._add_signal_interpretation(df)
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {str(e)}")
        
        return df
    
    def _add_signal_interpretation(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Add signal interpretation based on indicator values.
        
        Args:
            data: DataFrame with technical indicators
        
        Returns:
            DataFrame with signal columns
        """
        df = data.copy()
        
        # RSI Signals
        if 'RSI' in df.columns:
            df['RSI_Oversold'] = (df['RSI'] < self.config['rsi']['oversold']).astype(int)
            df['RSI_Overbought'] = (df['RSI'] > self.config['rsi']['overbought']).astype(int)
        
        # MACD Signals
        if 'MACD' in df.columns and 'MACD_Signal' in df.columns:
            df['MACD_Bullish'] = (df['MACD'] > df['MACD_Signal']).astype(int)
            df['MACD_Cross_Up'] = ((df['MACD'] > df['MACD_Signal']) & 
                                  (df['MACD'].shift(1) <= df['MACD_Signal'].shift(1))).astype(int)
            df['MACD_Cross_Down'] = ((df['MACD'] < df['MACD_Signal']) & 
                                    (df['MACD'].shift(1) >= df['MACD_Signal'].shift(1))).astype(int)
        
        # Bollinger Bands Signals
        if all(col in df.columns for col in ['BB_Upper', 'BB_Lower', 'Close']):
            df['BB_Squeeze'] = (df['BB_Width'] < df['BB_Width'].rolling(20).mean()).astype(int)
            df['BB_Upper_Touch'] = (df['Close'] >= df['BB_Upper']).astype(int)
            df['BB_Lower_Touch'] = (df['Close'] <= df['BB_Lower']).astype(int)
        
        # Stochastic Signals
        if 'Stoch_K' in df.columns:
            df['Stoch_Oversold'] = (df['Stoch_K'] < 20).astype(int)
            df['Stoch_Overbought'] = (df['Stoch_K'] > 80).astype(int)
        
        # ADX Signals
        if 'ADX' in df.columns:
            df['Strong_Trend'] = (df['ADX'] > 25).astype(int)
            df['Very_Strong_Trend'] = (df['ADX'] > 40).astype(int)
        
        # Volume Signals
        if 'Volume' in df.columns:
            df['High_Volume'] = (df['Volume'] > df['Volume'].rolling(20).mean() * 1.5).astype(int)
        
        return df


if __name__ == "__main__":
    # Example usage
    from ..data import DataCollector
    
    collector = DataCollector()
    analyzer = TechnicalAnalyzer()
    
    # Get sample data
    data = collector.fetch_stock_data('AAPL')
    
    if data is not None:
        print("Original data shape:", data.shape)
        
        # Calculate all indicators
        data_with_indicators = analyzer.calculate_all_indicators(data)
        
        print("Data with indicators shape:", data_with_indicators.shape)
        print("New columns added:", set(data_with_indicators.columns) - set(data.columns))
        
        # Show recent RSI and MACD values
        recent_data = data_with_indicators.tail(5)[['Close', 'RSI', 'MACD', 'MACD_Signal']]
        print("\nRecent indicator values:")
        print(recent_data)