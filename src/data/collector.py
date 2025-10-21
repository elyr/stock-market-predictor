"""
Data collection module for fetching stock market data.
Handles multiple data sources with error handling and caching.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import requests
from typing import List, Dict, Optional, Tuple
import logging
from datetime import datetime, timedelta
import time
import os
from alpha_vantage.timeseries import TimeSeries
from alpha_vantage.fundamentaldata import FundamentalData
from alpha_vantage.techindicators import TechIndicators
import yaml

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataCollector:
    """
    Main data collection class that fetches stock data from multiple sources.
    """
    
    def __init__(self, config_path: str = "config/config.yaml"):
        """Initialize the data collector with configuration."""
        self.config = self._load_config(config_path)
        self.cache = {}
        self.rate_limits = self.config['api_config']['rate_limits']
        self.last_request_time = {}
        
        # Initialize Alpha Vantage API if key is available
        alpha_vantage_key = os.getenv('ALPHA_VANTAGE_API_KEY')
        if alpha_vantage_key:
            self.av_ts = TimeSeries(key=alpha_vantage_key)
            self.av_fd = FundamentalData(key=alpha_vantage_key)
            self.av_ti = TechIndicators(key=alpha_vantage_key)
        else:
            logger.warning("Alpha Vantage API key not found. Some features may be limited.")
            self.av_ts = None
            self.av_fd = None
            self.av_ti = None
    
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file."""
        try:
            with open(config_path, 'r') as file:
                return yaml.safe_load(file)
        except FileNotFoundError:
            logger.error(f"Config file not found: {config_path}")
            raise
    
    def _respect_rate_limit(self, source: str) -> None:
        """Implement rate limiting for API calls."""
        if source not in self.last_request_time:
            self.last_request_time[source] = 0
        
        if source == 'yfinance':
            min_interval = 3600 / self.rate_limits['yfinance']  # seconds between requests
        elif source == 'alpha_vantage':
            min_interval = 86400 / self.rate_limits['alpha_vantage']  # seconds between requests
        else:
            min_interval = 1
        
        time_since_last = time.time() - self.last_request_time[source]
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            time.sleep(sleep_time)
        
        self.last_request_time[source] = time.time()
    
    def fetch_stock_data(self, symbol: str, period: str = "6mo") -> Optional[pd.DataFrame]:
        """
        Fetch historical stock data for a given symbol.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            period: Time period ('1d', '5d', '1mo', '3mo', '6mo', '1y', etc.)
        
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
            self._respect_rate_limit('yfinance')
            
            ticker = yf.Ticker(symbol)
            data = ticker.history(period=period, interval='1d')
            
            if data.empty:
                logger.warning(f"No data found for symbol: {symbol}")
                return None
            
            # Add symbol column
            data['Symbol'] = symbol
            
            # Cache the data
            self.cache[cache_key] = (datetime.now(), data)
            
            logger.info(f"Successfully fetched data for {symbol}")
            return data
            
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
        Fetch overall market indicators.
        
        Returns:
            Dictionary of market indicators
        """
        market_symbols = {
            'SPY': 'S&P 500',
            'QQQ': 'NASDAQ',
            'DIA': 'Dow Jones',
            'VIX': 'Volatility Index',
            'GLD': 'Gold',
            'TLT': '20+ Year Treasury'
        }
        
        market_data = {}
        
        for symbol, name in market_symbols.items():
            try:
                self._respect_rate_limit('yfinance')
                ticker = yf.Ticker(symbol)
                data = ticker.history(period='2d', interval='1d')
                
                if len(data) >= 2:
                    current_price = data['Close'].iloc[-1]
                    previous_price = data['Close'].iloc[-2]
                    change_pct = ((current_price - previous_price) / previous_price) * 100
                    
                    market_data[symbol] = {
                        'price': current_price,
                        'change_pct': change_pct,
                        'name': name
                    }
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error fetching market data for {symbol}: {str(e)}")
        
        return market_data
    
    def fetch_company_info(self, symbol: str) -> Optional[Dict]:
        """
        Fetch company information and key metrics.
        
        Args:
            symbol: Stock symbol
        
        Returns:
            Dictionary of company information
        """
        try:
            self._respect_rate_limit('yfinance')
            
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Extract key metrics
            company_data = {
                'symbol': symbol,
                'name': info.get('longName', 'N/A'),
                'sector': info.get('sector', 'N/A'),
                'industry': info.get('industry', 'N/A'),
                'market_cap': info.get('marketCap', 0),
                'pe_ratio': info.get('trailingPE', None),
                'forward_pe': info.get('forwardPE', None),
                'peg_ratio': info.get('pegRatio', None),
                'price_to_book': info.get('priceToBook', None),
                'price_to_sales': info.get('priceToSalesTrailing12Months', None),
                'debt_to_equity': info.get('debtToEquity', None),
                'return_on_equity': info.get('returnOnEquity', None),
                'profit_margin': info.get('profitMargins', None),
                'beta': info.get('beta', None),
                'avg_volume': info.get('averageVolume', 0),
                'dividend_yield': info.get('dividendYield', None),
                'recommendation': info.get('recommendationMean', None)
            }
            
            return company_data
            
        except Exception as e:
            logger.error(f"Error fetching company info for {symbol}: {str(e)}")
            return None
    
    def fetch_earnings_calendar(self, symbols: List[str]) -> pd.DataFrame:
        """
        Fetch upcoming earnings dates for given symbols.
        
        Args:
            symbols: List of stock symbols
        
        Returns:
            DataFrame with earnings calendar data
        """
        earnings_data = []
        
        for symbol in symbols:
            try:
                self._respect_rate_limit('yfinance')
                
                ticker = yf.Ticker(symbol)
                calendar = ticker.calendar
                
                if calendar is not None and not calendar.empty:
                    earnings_data.append({
                        'symbol': symbol,
                        'earnings_date': calendar.index[0] if len(calendar.index) > 0 else None,
                        'eps_estimate': calendar.iloc[0, 0] if calendar.shape[1] > 0 else None
                    })
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"Could not fetch earnings calendar for {symbol}: {str(e)}")
        
        return pd.DataFrame(earnings_data)
    
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