"""
Data collection module for fetching stock market data.
Handles Alpha Vantage API exclusively with error handling and caching.
"""

import pandas as pd
import numpy as np
import requests
from typing import List, Dict, Optional, Tuple
import logging
from datetime import datetime, timedelta
import time
import os
from dotenv import load_dotenv
import yaml

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataCollector:
    """
    Main data collection class that fetches stock data from Alpha Vantage exclusively.
    """
    
    def __init__(self, config_path: str = "config/config.yaml", alpha_vantage_key: str = None):
        """Initialize the data collector with Alpha Vantage configuration."""
        self.config = self._load_config(config_path)
        self.cache = {}
        
        # Initialize Alpha Vantage API
        self.alpha_vantage_key = alpha_vantage_key or os.getenv('ALPHA_VANTAGE_API_KEY')
        
        if not self.alpha_vantage_key:
            raise ValueError("Alpha Vantage API key is required. Set ALPHA_VANTAGE_API_KEY in .env file")
        
        self.base_url = "https://www.alphavantage.co/query"
        
        # Rate limiting (5 requests per minute for free tier)
        self.last_request_time = 0
        self.min_request_interval = 12  # 12 seconds between requests
        
        logger.info(f"Data Collector initialized with Alpha Vantage key: {self.alpha_vantage_key[:8]}***")
    
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file."""
        try:
            with open(config_path, 'r') as file:
                return yaml.safe_load(file)
        except FileNotFoundError:
            logger.warning(f"Config file not found: {config_path}, using defaults")
            return {'api_config': {'rate_limits': {'alpha_vantage': 500}}}
    
    def _rate_limit(self):
        """Implement rate limiting for Alpha Vantage API calls."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval:
            sleep_time = self.min_request_interval - elapsed
            print(f"⏳ Rate limiting: waiting {sleep_time:.1f}s...")
            time.sleep(sleep_time)
        self.last_request_time = time.time()
    
    def fetch_stock_data(self, symbol: str, period: str = "6mo") -> Optional[pd.DataFrame]:
        """
        Fetch historical stock data for a given symbol using Alpha Vantage.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            period: Time period (converted to Alpha Vantage format)
        
        Returns:
            DataFrame with OHLCV data
        """
        cache_key = f"{symbol}_{period}"
        
        # Check cache first
        if cache_key in self.cache:
            cache_time, data = self.cache[cache_key]
            if datetime.now() - cache_time < timedelta(minutes=15):  # 15-minute cache
                return data
        
        try:
            self._rate_limit()
            
            # Use daily data from Alpha Vantage
            params = {
                'function': 'TIME_SERIES_DAILY',
                'symbol': symbol,
                'apikey': self.alpha_vantage_key,
                'outputsize': 'full'  # Get full historical data
            }
            
            response = requests.get(self.base_url, params=params, timeout=15)
            data_json = response.json()
            
            if 'Time Series (Daily)' in data_json:
                df = pd.DataFrame.from_dict(data_json['Time Series (Daily)'], orient='index')
                df.index = pd.to_datetime(df.index)
                df = df.astype(float)
                df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                df = df.sort_index()
                
                # Filter based on period
                if period != 'max':
                    days_map = {
                        '1d': 1, '5d': 5, '1mo': 30, '3mo': 90, 
                        '6mo': 180, '1y': 365, '2y': 730, '5y': 1825
                    }
                    days = days_map.get(period, 180)
                    cutoff_date = datetime.now() - timedelta(days=days)
                    df = df[df.index >= cutoff_date]
                
                if df.empty:
                    logger.warning(f"No data found for symbol: {symbol}")
                    return None
                
                # Add symbol column
                df['Symbol'] = symbol
                
                # Cache the data
                self.cache[cache_key] = (datetime.now(), df)
                
                logger.info(f"Successfully fetched data for {symbol}")
                return df
            else:
                error_msg = data_json.get('Information', data_json.get('Error Message', 'Unknown error'))
                logger.warning(f"Alpha Vantage API issue for {symbol}: {error_msg}")
                return None
            
        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {str(e)}")
            return None
    
    def fetch_multiple_stocks(self, symbols: List[str], period: str = "6mo") -> Dict[str, pd.DataFrame]:
        """
        Fetch data for multiple stocks.
        
        Args:
            symbols: List of stock symbols
            period: Time period
        
        Returns:
            Dictionary mapping symbols to their data
        """
        stock_data = {}
        
        for symbol in symbols:
            data = self.fetch_stock_data(symbol, period)
            if data is not None:
                stock_data[symbol] = data
            time.sleep(0.1)  # Small delay to be respectful
        
        logger.info(f"Fetched data for {len(stock_data)}/{len(symbols)} symbols")
        return stock_data
    
    def fetch_market_data(self) -> Dict[str, float]:
        """
        Fetch overall market indicators using Alpha Vantage.
        
        Returns:
            Dictionary of market indicators
        """
        market_symbols = {
            'SPY': 'S&P 500',
            'QQQ': 'NASDAQ',
            'DIA': 'Dow Jones',
            '^VIX': 'Volatility Index',
            'GLD': 'Gold',
            'TLT': '20+ Year Treasury'
        }
        
        market_data = {}
        
        for symbol, name in market_symbols.items():
            try:
                self._rate_limit()
                
                # Use Alpha Vantage for market data
                params = {
                    'function': 'GLOBAL_QUOTE',
                    'symbol': symbol,
                    'apikey': self.alpha_vantage_key
                }
                
                response = requests.get(self.base_url, params=params, timeout=15)
                data_json = response.json()
                
                if 'Global Quote' in data_json:
                    quote = data_json['Global Quote']
                    current_price = float(quote.get('05. price', 0))
                    change_pct = float(quote.get('10. change percent', '0%').replace('%', ''))
                    
                    market_data[symbol] = {
                        'price': current_price,
                        'change_pct': change_pct,
                        'name': name
                    }
                else:
                    logger.warning(f"Alpha Vantage API issue for {symbol}: {data_json.get('Information', 'Unknown error')}")
                
            except Exception as e:
                logger.error(f"Error fetching market data for {symbol}: {str(e)}")
        
        return market_data
    
    def fetch_company_info(self, symbol: str) -> Optional[Dict]:
        """
        Fetch basic company information.
        
        Args:
            symbol: Stock symbol
        
        Returns:
            Dictionary of company information (basic for Alpha Vantage free tier)
        """
        try:
            # For Alpha Vantage free tier, return basic info
            # Real company fundamentals would require premium Alpha Vantage or other APIs
            company_data = {
                'symbol': symbol,
                'name': 'N/A',  # Would need company overview API (premium)
                'sector': 'N/A',
                'industry': 'N/A', 
                'market_cap': 0,
                'pe_ratio': None,
                'forward_pe': None,
                'peg_ratio': None,
                'price_to_book': None,
                'price_to_sales': None,
                'debt_to_equity': None,
                'return_on_equity': None,
                'profit_margin': None,
                'beta': None,
                'avg_volume': 0,
                'dividend_yield': None,
                'recommendation': None
            }
            
            logger.info(f"Basic company info retrieved for {symbol}")
            return company_data
            
        except Exception as e:
            logger.error(f"Error fetching company info for {symbol}: {str(e)}")
            return None
    
    def fetch_earnings_calendar(self, symbols: List[str]) -> pd.DataFrame:
        """
        Fetch upcoming earnings dates for given symbols (simplified for Alpha Vantage free tier).
        
        Args:
            symbols: List of stock symbols
        
        Returns:
            DataFrame with basic earnings calendar data
        """
        # For Alpha Vantage free tier, return empty dataframe
        # Real earnings calendar would require premium features
        logger.info("Earnings calendar not available with Alpha Vantage free tier")
        return pd.DataFrame()
    
    def fetch_insider_transactions(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Fetch insider trading data.
        
        Args:
            symbol: Stock symbol
        
        Returns:
            DataFrame with insider transactions
        """
        try:
            self._respect_rate_limit('yfinance')
            
            ticker = yf.Ticker(symbol)
            insider_transactions = ticker.insider_transactions
            
            if insider_transactions is not None and not insider_transactions.empty:
                return insider_transactions
            
        except Exception as e:
            logger.warning(f"Could not fetch insider transactions for {symbol}: {str(e)}")
        
        return None
    
    def get_stock_news(self, symbol: str, num_articles: int = 5) -> List[Dict]:
        """
        Fetch recent news for a stock.
        
        Args:
            symbol: Stock symbol
            num_articles: Number of articles to fetch
        
        Returns:
            List of news articles
        """
        try:
            self._respect_rate_limit('yfinance')
            
            ticker = yf.Ticker(symbol)
            news = ticker.news[:num_articles]
            
            return news
            
        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {str(e)}")
            return []
    
    def save_data_to_csv(self, data: Dict[str, pd.DataFrame], filename: str) -> None:
        """
        Save stock data to CSV files.
        
        Args:
            data: Dictionary of stock data
            filename: Base filename for saving
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            for symbol, df in data.items():
                file_path = f"data/{symbol}_{filename}_{timestamp}.csv"
                df.to_csv(file_path)
                logger.info(f"Saved data for {symbol} to {file_path}")
                
        except Exception as e:
            logger.error(f"Error saving data: {str(e)}")
    
    def clear_cache(self) -> None:
        """Clear the data cache."""
        self.cache.clear()
        logger.info("Data cache cleared")


if __name__ == "__main__":
    # Example usage
    collector = DataCollector()
    
    # Test with a few symbols
    test_symbols = ['AAPL', 'MSFT', 'GOOGL']
    
    print("Fetching stock data...")
    stock_data = collector.fetch_multiple_stocks(test_symbols)
    
    print("Fetching market data...")
    market_data = collector.fetch_market_data()
    print(market_data)
    
    print("Fetching company info...")
    for symbol in test_symbols:
        info = collector.fetch_company_info(symbol)
        if info:
            print(f"{symbol}: {info['name']} - Sector: {info['sector']}")