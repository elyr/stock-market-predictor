"""
Data collection module for fetching stock market data.
Handles multiple data sources with error handling and caching.
"""

import yfinance as yf
import pandas as pd
from typing import List, Dict, Optional
import logging
from datetime import datetime, timedelta
import time
import os
from alpha_vantage.timeseries import TimeSeries
from alpha_vantage.fundamentaldata import FundamentalData
from alpha_vantage.techindicators import TechIndicators
import yaml
from src.data.providers import default_providers

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_API_CONFIG = {
    'rate_limits': {'yfinance': 7200, 'alpha_vantage': 500},
    'retry_attempts': 3,
    'timeout': 30,
}


def resolve_config_path(config_path: str) -> str:
    """Resolve a config path relative to the CWD, falling back to the project root."""
    if os.path.isabs(config_path) or os.path.exists(config_path):
        return config_path
    candidate = os.path.join(PROJECT_ROOT, config_path)
    return candidate if os.path.exists(candidate) else config_path


def load_config(config_path: str) -> Dict:
    """Load a YAML config file, returning {} (and logging) if it is missing."""
    path = resolve_config_path(config_path)
    try:
        with open(path, 'r') as file:
            return yaml.safe_load(file) or {}
    except FileNotFoundError:
        logger.warning(f"Config file not found: {config_path}. Using defaults.")
        return {}


class DataCollector:
    """
    Main data collection class that fetches stock data from multiple sources.
    """
    
    def __init__(self, config_path: str = "config/config.yaml"):
        """Initialize the data collector with configuration."""
        self.config = load_config(config_path)
        self.cache = {}
        self.info_cache = {}
        api_config = {**DEFAULT_API_CONFIG, **self.config.get('api_config', {})}
        self.rate_limits = {**DEFAULT_API_CONFIG['rate_limits'], **api_config.get('rate_limits', {})}
        self.retry_attempts = api_config.get('retry_attempts', 3)
        self.last_request_time = {}
        # Fallback price sources when Yahoo Finance fails (see src/data/providers.py)
        self.providers = default_providers() if api_config.get('fallback', True) else []
        self.source_counts: Dict[str, int] = {}     # series fetched, by source (since start)
        self.source_failures: Dict[str, int] = {}   # failed attempts, by source
        self.run_sources: Dict[str, int] = {}       # series fetched, by source, since reset_run_sources()
        
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
        
        for attempt in range(1, self.retry_attempts + 1):
            try:
                self._respect_rate_limit('yfinance')
                
                ticker = yf.Ticker(symbol)
                data = ticker.history(period=period, interval='1d')
                
                if data.empty:
                    logger.warning(f"No data found for symbol: {symbol}")
                    self._count(self.source_failures, 'Yahoo Finance')
                    return self._fallback(symbol, period, cache_key)
                
                # Use timezone-naive dates so stocks from different exchanges align
                if getattr(data.index, 'tz', None) is not None:
                    data.index = data.index.tz_localize(None)
                data.index = data.index.normalize()
                
                # Add symbol column
                data['Symbol'] = symbol
                
                # Cache the data
                self.cache[cache_key] = (datetime.now(), data)
                self._record_source('Yahoo Finance')

                logger.info(f"Successfully fetched data for {symbol}")
                return data

            except Exception as e:
                logger.warning(f"Error fetching data for {symbol} (attempt {attempt}): {str(e)}")
                if attempt < self.retry_attempts:
                    time.sleep(2 ** attempt)

        self._count(self.source_failures, 'Yahoo Finance')
        logger.error(f"Yahoo Finance gave nothing for {symbol} after {self.retry_attempts} attempts")
        return self._fallback(symbol, period, cache_key)

    # ------------------------------------------------------------ fallbacks

    @staticmethod
    def _count(counts: Dict[str, int], source: str) -> None:
        counts[source] = counts.get(source, 0) + 1

    def _record_source(self, source: str) -> None:
        self._count(self.source_counts, source)
        self._count(self.run_sources, source)

    def reset_run_sources(self) -> None:
        """Start counting where prices come from, for one analysis."""
        self.run_sources = {}

    def _fallback(self, symbol: str, period: str, cache_key: str) -> Optional[pd.DataFrame]:
        """Ask the fallback providers in order; the first usable series wins."""
        for provider in self.providers:
            if not provider.supports(symbol):
                continue
            try:
                data = provider.fetch(symbol, period)
            except Exception as e:
                self._count(self.source_failures, provider.name)
                logger.warning(f"{provider.name} could not provide {symbol}: {e}")
                continue
            if data is not None and not data.empty:
                self.cache[cache_key] = (datetime.now(), data)
                self._record_source(provider.name)
                logger.warning(f"Prices for {symbol} came from {provider.name} (Yahoo Finance unavailable)")
                return data
            self._count(self.source_failures, provider.name)
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
            '^VIX': 'Volatility Index',
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
        if symbol in self.info_cache:
            return self.info_cache[symbol]
        
        try:
            self._respect_rate_limit('yfinance')
            
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            
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
            
            self.info_cache[symbol] = company_data
            return company_data
            
        except Exception as e:
            logger.error(f"Error fetching company info for {symbol}: {str(e)}")
            return None
    
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