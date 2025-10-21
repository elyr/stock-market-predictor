# Utility functions for the Stock Prediction System
"""
Utility functions and helpers for the Stock Prediction System.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
import logging
from datetime import datetime, timedelta
import os
import json
import pickle
import time

logger = logging.getLogger(__name__)


def setup_logging(log_level: str = "INFO", log_file: str = "logs/stock_predictor.log"):
    """
    Set up logging configuration.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Path to log file
    """
    # Create logs directory if it doesn't exist
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )


def validate_symbols(symbols: List[str]) -> List[str]:
    """
    Validate and clean stock symbols.
    
    Args:
        symbols: List of stock symbols
    
    Returns:
        List of validated symbols
    """
    valid_symbols = []
    
    for symbol in symbols:
        # Clean and validate symbol
        clean_symbol = symbol.strip().upper()
        
        # Basic validation (alphanumeric, 1-5 characters)
        if clean_symbol.isalnum() and 1 <= len(clean_symbol) <= 5:
            valid_symbols.append(clean_symbol)
        else:
            logger.warning(f"Invalid symbol: {symbol}")
    
    return valid_symbols


def calculate_percentage_change(old_value: float, new_value: float) -> float:
    """
    Calculate percentage change between two values.
    
    Args:
        old_value: Original value
        new_value: New value
    
    Returns:
        Percentage change
    """
    if old_value == 0:
        return 0.0
    
    return ((new_value - old_value) / old_value) * 100


def format_currency(amount: float, currency: str = "USD") -> str:
    """
    Format amount as currency.
    
    Args:
        amount: Amount to format
        currency: Currency code
    
    Returns:
        Formatted currency string
    """
    if currency == "USD":
        return f"${amount:,.2f}"
    else:
        return f"{amount:,.2f} {currency}"


def format_large_number(number: float) -> str:
    """
    Format large numbers with K, M, B suffixes.
    
    Args:
        number: Number to format
    
    Returns:
        Formatted number string
    """
    if abs(number) >= 1e9:
        return f"{number/1e9:.1f}B"
    elif abs(number) >= 1e6:
        return f"{number/1e6:.1f}M"
    elif abs(number) >= 1e3:
        return f"{number/1e3:.1f}K"
    else:
        return f"{number:.0f}"


def get_trading_days_between(start_date: datetime, end_date: datetime) -> int:
    """
    Calculate number of trading days between two dates (excluding weekends).
    
    Args:
        start_date: Start date
        end_date: End date
    
    Returns:
        Number of trading days
    """
    trading_days = 0
    current_date = start_date
    
    while current_date <= end_date:
        # Skip weekends (Saturday = 5, Sunday = 6)
        if current_date.weekday() < 5:
            trading_days += 1
        current_date += timedelta(days=1)
    
    return trading_days


def is_market_open(current_time: datetime = None) -> bool:
    """
    Check if the US stock market is currently open.
    
    Args:
        current_time: Time to check (uses current time if None)
    
    Returns:
        True if market is open
    """
    if current_time is None:
        current_time = datetime.now()
    
    # Convert to ET (market timezone)
    # Note: This is a simplified check - doesn't account for holidays
    weekday = current_time.weekday()
    hour = current_time.hour
    
    # Market is closed on weekends
    if weekday >= 5:  # Saturday = 5, Sunday = 6
        return False
    
    # Market hours: 9:30 AM - 4:00 PM ET
    # Simplified check (assumes local time is ET)
    market_open = 9.5  # 9:30 AM
    market_close = 16.0  # 4:00 PM
    
    return market_open <= hour < market_close


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safely divide two numbers, returning default if denominator is zero.
    
    Args:
        numerator: Numerator
        denominator: Denominator
        default: Default value if division by zero
    
    Returns:
        Division result or default
    """
    if denominator == 0:
        return default
    return numerator / denominator


def normalize_score(value: float, min_val: float, max_val: float) -> float:
    """
    Normalize a value to 0-100 scale.
    
    Args:
        value: Value to normalize
        min_val: Minimum possible value
        max_val: Maximum possible value
    
    Returns:
        Normalized value (0-100)
    """
    if max_val == min_val:
        return 50.0  # Return neutral score
    
    normalized = ((value - min_val) / (max_val - min_val)) * 100
    return max(0, min(100, normalized))


def calculate_volatility(prices: pd.Series, window: int = 20) -> float:
    """
    Calculate annualized volatility from price series.
    
    Args:
        prices: Series of prices
        window: Window for calculation
    
    Returns:
        Annualized volatility
    """
    if len(prices) < 2:
        return 0.0
    
    returns = prices.pct_change().dropna()
    if len(returns) == 0:
        return 0.0
    
    volatility = returns.std() * np.sqrt(252)  # Annualized
    return volatility


def calculate_sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """
    Calculate Sharpe ratio from returns series.
    
    Args:
        returns: Series of returns
        risk_free_rate: Risk-free rate (annualized)
    
    Returns:
        Sharpe ratio
    """
    if len(returns) == 0:
        return 0.0
    
    excess_returns = returns - (risk_free_rate / 252)  # Daily risk-free rate
    
    if excess_returns.std() == 0:
        return 0.0
    
    return (excess_returns.mean() / excess_returns.std()) * np.sqrt(252)


def save_to_cache(data: Any, filename: str, cache_dir: str = "data/cache") -> bool:
    """
    Save data to cache file.
    
    Args:
        data: Data to save
        filename: Cache filename
        cache_dir: Cache directory
    
    Returns:
        True if successful
    """
    try:
        os.makedirs(cache_dir, exist_ok=True)
        filepath = os.path.join(cache_dir, filename)
        
        if filename.endswith('.json'):
            with open(filepath, 'w') as f:
                json.dump(data, f, default=str)
        elif filename.endswith('.pkl'):
            with open(filepath, 'wb') as f:
                pickle.dump(data, f)
        else:
            # Assume it's a pandas DataFrame
            data.to_csv(filepath, index=False)
        
        return True
        
    except Exception as e:
        logger.error(f"Error saving to cache: {str(e)}")
        return False


def load_from_cache(filename: str, cache_dir: str = "data/cache", 
                   max_age_hours: int = 24) -> Optional[Any]:
    """
    Load data from cache file if it exists and is not too old.
    
    Args:
        filename: Cache filename
        cache_dir: Cache directory
        max_age_hours: Maximum age of cache file in hours
    
    Returns:
        Cached data or None
    """
    try:
        filepath = os.path.join(cache_dir, filename)
        
        if not os.path.exists(filepath):
            return None
        
        # Check file age
        file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(filepath))
        if file_age > timedelta(hours=max_age_hours):
            return None
        
        if filename.endswith('.json'):
            with open(filepath, 'r') as f:
                return json.load(f)
        elif filename.endswith('.pkl'):
            with open(filepath, 'rb') as f:
                return pickle.load(f)
        else:
            # Assume it's a CSV file
            return pd.read_csv(filepath)
        
    except Exception as e:
        logger.error(f"Error loading from cache: {str(e)}")
        return None


def clean_dataframe(df: pd.DataFrame, remove_outliers: bool = True, 
                   outlier_threshold: float = 3.0) -> pd.DataFrame:
    """
    Clean DataFrame by removing NaN values and optionally outliers.
    
    Args:
        df: DataFrame to clean
        remove_outliers: Whether to remove outliers
        outlier_threshold: Z-score threshold for outlier detection
    
    Returns:
        Cleaned DataFrame
    """
    # Remove rows with too many NaN values
    df_clean = df.dropna(thresh=len(df.columns) * 0.5)
    
    # Fill remaining NaN values
    numeric_columns = df_clean.select_dtypes(include=[np.number]).columns
    df_clean[numeric_columns] = df_clean[numeric_columns].fillna(df_clean[numeric_columns].median())
    
    if remove_outliers:
        # Remove outliers using Z-score
        for col in numeric_columns:
            z_scores = np.abs((df_clean[col] - df_clean[col].mean()) / df_clean[col].std())
            df_clean = df_clean[z_scores < outlier_threshold]
    
    return df_clean


def get_market_status() -> Dict[str, Any]:
    """
    Get current market status information.
    
    Returns:
        Dictionary with market status information
    """
    now = datetime.now()
    
    return {
        'current_time': now.strftime('%Y-%m-%d %H:%M:%S'),
        'is_open': is_market_open(now),
        'is_weekend': now.weekday() >= 5,
        'next_open': get_next_market_open(now),
        'next_close': get_next_market_close(now)
    }


def get_next_market_open(current_time: datetime) -> str:
    """Get next market open time."""
    # Simplified logic - doesn't account for holidays
    if current_time.weekday() >= 5:  # Weekend
        days_until_monday = 7 - current_time.weekday()
        next_open = current_time + timedelta(days=days_until_monday)
        next_open = next_open.replace(hour=9, minute=30, second=0, microsecond=0)
    else:  # Weekday
        if current_time.hour < 9 or (current_time.hour == 9 and current_time.minute < 30):
            # Market hasn't opened today
            next_open = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
        else:
            # Market already opened/closed today, next open is tomorrow
            next_open = current_time + timedelta(days=1)
            next_open = next_open.replace(hour=9, minute=30, second=0, microsecond=0)
            
            # Skip weekend
            if next_open.weekday() >= 5:
                days_to_add = 7 - next_open.weekday()
                next_open += timedelta(days=days_to_add)
    
    return next_open.strftime('%Y-%m-%d %H:%M:%S')


def get_next_market_close(current_time: datetime) -> str:
    """Get next market close time."""
    # Simplified logic
    if current_time.weekday() >= 5:  # Weekend
        days_until_monday = 7 - current_time.weekday()
        next_close = current_time + timedelta(days=days_until_monday)
        next_close = next_close.replace(hour=16, minute=0, second=0, microsecond=0)
    else:  # Weekday
        if current_time.hour < 16:
            # Market hasn't closed today
            next_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
        else:
            # Market already closed today, next close is tomorrow
            next_close = current_time + timedelta(days=1)
            next_close = next_close.replace(hour=16, minute=0, second=0, microsecond=0)
            
            # Skip weekend
            if next_close.weekday() >= 5:
                days_to_add = 7 - next_close.weekday()
                next_close += timedelta(days=days_to_add)
    
    return next_close.strftime('%Y-%m-%d %H:%M:%S')


# Decorators for common functionality

def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    """
    Decorator to retry function on failure.
    
    Args:
        max_retries: Maximum number of retries
        delay: Delay between retries in seconds
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries:
                        logger.error(f"Function {func.__name__} failed after {max_retries} retries: {str(e)}")
                        raise
                    else:
                        logger.warning(f"Function {func.__name__} failed (attempt {attempt + 1}), retrying...")
                        time.sleep(delay)
            return None
        return wrapper
    return decorator


def timing_decorator(func):
    """Decorator to measure function execution time."""
    def wrapper(*args, **kwargs):
        start_time = datetime.now()
        result = func(*args, **kwargs)
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        logger.info(f"Function {func.__name__} executed in {execution_time:.2f} seconds")
        return result
    return wrapper