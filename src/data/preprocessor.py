"""
Data preprocessing module for cleaning and preparing stock data for analysis.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
import logging
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class DataPreprocessor:
    """
    Handles data cleaning, feature engineering, and preprocessing for stock analysis.
    """
    
    def __init__(self):
        self.scaler = StandardScaler()
        self.price_scaler = MinMaxScaler()
    
    def clean_stock_data(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Clean and validate stock data.
        
        Args:
            data: Raw stock data DataFrame
        
        Returns:
            Cleaned DataFrame
        """
        if data.empty:
            return data
        
        # Remove any duplicate dates
        data = data.loc[~data.index.duplicated(keep='first')]
        
        # Sort by date
        data = data.sort_index()
        
        # Handle missing values
        data = data.fillna(method='ffill').fillna(method='bfill')
        
        # Remove outliers (prices that changed more than 50% in a day)
        for col in ['Open', 'High', 'Low', 'Close']:
            if col in data.columns:
                pct_change = data[col].pct_change().abs()
                outlier_mask = pct_change > 0.5
                if outlier_mask.sum() > 0:
                    logger.warning(f"Found {outlier_mask.sum()} outliers in {col}")
                    # Replace outliers with previous value
                    data.loc[outlier_mask, col] = data.loc[outlier_mask, col].shift(1)
        
        # Ensure volume is positive
        if 'Volume' in data.columns:
            data.loc[data['Volume'] <= 0, 'Volume'] = data['Volume'].median()
        
        return data
    
    def add_basic_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Add basic financial features to stock data.
        
        Args:
            data: Stock data DataFrame
        
        Returns:
            DataFrame with additional features
        """
        df = data.copy()
        
        # Price-based features
        df['Price_Range'] = df['High'] - df['Low']
        df['Price_Change'] = df['Close'] - df['Open']
        df['Price_Change_Pct'] = df['Price_Change'] / df['Open']
        
        # Returns
        df['Daily_Return'] = df['Close'].pct_change()
        df['Log_Return'] = np.log(df['Close'] / df['Close'].shift(1))
        
        # Volatility (rolling standard deviation of returns)
        df['Volatility_5d'] = df['Daily_Return'].rolling(window=5).std()
        df['Volatility_20d'] = df['Daily_Return'].rolling(window=20).std()
        
        # Volume features
        if 'Volume' in df.columns:
            df['Volume_MA_20'] = df['Volume'].rolling(window=20).mean()
            df['Volume_Ratio'] = df['Volume'] / df['Volume_MA_20']
            df['Price_Volume'] = df['Close'] * df['Volume']
        
        # Gap analysis
        df['Gap_Up'] = (df['Open'] > df['Close'].shift(1)).astype(int)
        df['Gap_Down'] = (df['Open'] < df['Close'].shift(1)).astype(int)
        df['Gap_Size'] = df['Open'] - df['Close'].shift(1)
        df['Gap_Size_Pct'] = df['Gap_Size'] / df['Close'].shift(1)
        
        # True Range (for ATR calculation)
        df['True_Range'] = np.maximum(
            df['High'] - df['Low'],
            np.maximum(
                abs(df['High'] - df['Close'].shift(1)),
                abs(df['Low'] - df['Close'].shift(1))
            )
        )
        
        return df
    
    def add_moving_averages(self, data: pd.DataFrame, periods: List[int] = None) -> pd.DataFrame:
        """
        Add various moving averages to the data.
        
        Args:
            data: Stock data DataFrame
            periods: List of periods for moving averages
        
        Returns:
            DataFrame with moving averages
        """
        if periods is None:
            periods = [5, 10, 20, 50, 200]
        
        df = data.copy()
        
        for period in periods:
            # Simple Moving Average
            df[f'SMA_{period}'] = df['Close'].rolling(window=period).mean()
            
            # Exponential Moving Average
            df[f'EMA_{period}'] = df['Close'].ewm(span=period).mean()
            
            # Volume Moving Average
            if 'Volume' in df.columns:
                df[f'Volume_SMA_{period}'] = df['Volume'].rolling(window=period).mean()
        
        # Moving average relationships
        if 'SMA_20' in df.columns and 'SMA_50' in df.columns:
            df['MA_Cross_20_50'] = (df['SMA_20'] > df['SMA_50']).astype(int)
        
        if 'SMA_50' in df.columns and 'SMA_200' in df.columns:
            df['MA_Cross_50_200'] = (df['SMA_50'] > df['SMA_200']).astype(int)
        
        # Price position relative to moving averages
        for period in [20, 50, 200]:
            if f'SMA_{period}' in df.columns:
                df[f'Price_Above_SMA_{period}'] = (df['Close'] > df[f'SMA_{period}']).astype(int)
                df[f'Price_Distance_SMA_{period}'] = (df['Close'] - df[f'SMA_{period}']) / df[f'SMA_{period}']
        
        return df
    
    def add_momentum_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Add momentum-based features.
        
        Args:
            data: Stock data DataFrame
        
        Returns:
            DataFrame with momentum features
        """
        df = data.copy()
        
        # Rate of Change (ROC)
        for period in [1, 5, 10, 20]:
            df[f'ROC_{period}d'] = ((df['Close'] - df['Close'].shift(period)) / df['Close'].shift(period)) * 100
        
        # Momentum (price difference over periods)
        for period in [5, 10, 20]:
            df[f'Momentum_{period}d'] = df['Close'] - df['Close'].shift(period)
        
        # Williams %R
        for period in [14, 20]:
            highest_high = df['High'].rolling(window=period).max()
            lowest_low = df['Low'].rolling(window=period).min()
            df[f'Williams_R_{period}'] = ((highest_high - df['Close']) / (highest_high - lowest_low)) * -100
        
        # Commodity Channel Index (CCI)
        for period in [14, 20]:
            typical_price = (df['High'] + df['Low'] + df['Close']) / 3
            ma_tp = typical_price.rolling(window=period).mean()
            mad = typical_price.rolling(window=period).apply(lambda x: np.mean(np.abs(x - x.mean())))
            df[f'CCI_{period}'] = (typical_price - ma_tp) / (0.015 * mad)
        
        return df
    
    def add_pattern_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Add candlestick pattern and price action features.
        
        Args:
            data: Stock data DataFrame
        
        Returns:
            DataFrame with pattern features
        """
        df = data.copy()
        
        # Body and shadow calculations
        df['Body_Size'] = abs(df['Close'] - df['Open'])
        df['Upper_Shadow'] = df['High'] - np.maximum(df['Open'], df['Close'])
        df['Lower_Shadow'] = np.minimum(df['Open'], df['Close']) - df['Low']
        df['Body_Size_Pct'] = df['Body_Size'] / df['Close']
        
        # Candlestick patterns
        df['Doji'] = (df['Body_Size'] < (df['High'] - df['Low']) * 0.1).astype(int)
        df['Hammer'] = ((df['Lower_Shadow'] > df['Body_Size'] * 2) & 
                       (df['Upper_Shadow'] < df['Body_Size'] * 0.5)).astype(int)
        df['Shooting_Star'] = ((df['Upper_Shadow'] > df['Body_Size'] * 2) & 
                              (df['Lower_Shadow'] < df['Body_Size'] * 0.5)).astype(int)
        
        # Engulfing patterns
        df['Bullish_Engulfing'] = ((df['Close'] > df['Open']) & 
                                  (df['Close'].shift(1) < df['Open'].shift(1)) &
                                  (df['Open'] < df['Close'].shift(1)) &
                                  (df['Close'] > df['Open'].shift(1))).astype(int)
        
        df['Bearish_Engulfing'] = ((df['Close'] < df['Open']) & 
                                  (df['Close'].shift(1) > df['Open'].shift(1)) &
                                  (df['Open'] > df['Close'].shift(1)) &
                                  (df['Close'] < df['Open'].shift(1))).astype(int)
        
        # Price action patterns
        df['Higher_High'] = (df['High'] > df['High'].shift(1)).astype(int)
        df['Higher_Low'] = (df['Low'] > df['Low'].shift(1)).astype(int)
        df['Lower_High'] = (df['High'] < df['High'].shift(1)).astype(int)
        df['Lower_Low'] = (df['Low'] < df['Low'].shift(1)).astype(int)
        
        # Consecutive patterns
        df['Consecutive_Up'] = (df['Close'] > df['Close'].shift(1)).astype(int)
        df['Consecutive_Down'] = (df['Close'] < df['Close'].shift(1)).astype(int)
        
        # Count consecutive days
        for i in range(2, 6):  # 2-5 consecutive days
            df[f'Consecutive_Up_{i}d'] = (df['Consecutive_Up'].rolling(window=i).sum() == i).astype(int)
            df[f'Consecutive_Down_{i}d'] = (df['Consecutive_Down'].rolling(window=i).sum() == i).astype(int)
        
        return df
    
    def add_support_resistance(self, data: pd.DataFrame, window: int = 20) -> pd.DataFrame:
        """
        Add support and resistance levels.
        
        Args:
            data: Stock data DataFrame
            window: Lookback window for S/R calculation
        
        Returns:
            DataFrame with S/R features
        """
        df = data.copy()
        
        # Rolling support and resistance
        df['Resistance'] = df['High'].rolling(window=window).max()
        df['Support'] = df['Low'].rolling(window=window).min()
        
        # Distance to S/R levels
        df['Distance_to_Resistance'] = (df['Resistance'] - df['Close']) / df['Close']
        df['Distance_to_Support'] = (df['Close'] - df['Support']) / df['Close']
        
        # Breakout indicators
        df['Resistance_Break'] = (df['Close'] > df['Resistance'].shift(1)).astype(int)
        df['Support_Break'] = (df['Close'] < df['Support'].shift(1)).astype(int)
        
        # Position within range
        df['Range_Position'] = (df['Close'] - df['Support']) / (df['Resistance'] - df['Support'])
        
        return df
    
    def create_target_variable(self, data: pd.DataFrame, horizon: int = 1, 
                              threshold: float = 0.02) -> pd.DataFrame:
        """
        Create target variables for prediction.
        
        Args:
            data: Stock data DataFrame
            horizon: Number of days ahead to predict
            threshold: Minimum percentage change to consider as "up"
        
        Returns:
            DataFrame with target variables
        """
        df = data.copy()
        
        # Future price and return
        df['Future_Close'] = df['Close'].shift(-horizon)
        df['Future_Return'] = (df['Future_Close'] - df['Close']) / df['Close']
        
        # Binary target: will stock go up by threshold%?
        df['Target_Up'] = (df['Future_Return'] > threshold).astype(int)
        
        # Multi-class target
        df['Target_Direction'] = pd.cut(df['Future_Return'], 
                                       bins=[-np.inf, -threshold, threshold, np.inf],
                                       labels=['Down', 'Flat', 'Up'])
        
        # Regression target (future return)
        df['Target_Return'] = df['Future_Return']
        
        return df
    
    def prepare_features_for_ml(self, data: pd.DataFrame, 
                               feature_columns: List[str] = None) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prepare features for machine learning models.
        
        Args:
            data: Preprocessed DataFrame
            feature_columns: List of columns to use as features
        
        Returns:
            Tuple of (features, targets)
        """
        df = data.copy()
        
        # Remove rows with missing target
        df = df.dropna(subset=['Target_Up'])
        
        if feature_columns is None:
            # Auto-select numeric columns (excluding target and identifier columns)
            exclude_cols = ['Target_Up', 'Target_Direction', 'Target_Return', 
                           'Future_Close', 'Future_Return', 'Symbol']
            feature_columns = [col for col in df.select_dtypes(include=[np.number]).columns 
                             if col not in exclude_cols]
        
        # Prepare features
        X = df[feature_columns].fillna(0)  # Fill any remaining NaNs
        
        # Scale features
        X_scaled = self.scaler.fit_transform(X)
        
        # Prepare targets
        y = df['Target_Up'].values
        
        return X_scaled, y
    
    def get_feature_importance_names(self, data: pd.DataFrame) -> List[str]:
        """
        Get the names of features used for ML models.
        
        Args:
            data: Preprocessed DataFrame
        
        Returns:
            List of feature names
        """
        exclude_cols = ['Target_Up', 'Target_Direction', 'Target_Return', 
                       'Future_Close', 'Future_Return', 'Symbol']
        feature_columns = [col for col in data.select_dtypes(include=[np.number]).columns 
                          if col not in exclude_cols]
        return feature_columns


if __name__ == "__main__":
    # Example usage
    from collector import DataCollector
    
    collector = DataCollector()
    preprocessor = DataPreprocessor()
    
    # Get sample data
    data = collector.fetch_stock_data('AAPL')
    
    if data is not None:
        print("Original data shape:", data.shape)
        
        # Clean data
        data = preprocessor.clean_stock_data(data)
        
        # Add features
        data = preprocessor.add_basic_features(data)
        data = preprocessor.add_moving_averages(data)
        data = preprocessor.add_momentum_features(data)
        data = preprocessor.add_pattern_features(data)
        data = preprocessor.add_support_resistance(data)
        data = preprocessor.create_target_variable(data)
        
        print("Processed data shape:", data.shape)
        print("Feature columns:", len(preprocessor.get_feature_importance_names(data)))
        
        # Prepare for ML
        X, y = preprocessor.prepare_features_for_ml(data)
        print("ML features shape:", X.shape)
        print("Target distribution:", np.bincount(y))