"""
Test suite for the Stock Prediction System.
"""

import unittest
import pandas as pd
import numpy as np
import sys
import os

# Add src to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from data import DataCollector, DataPreprocessor
from analysis import TechnicalAnalyzer
from utils import helpers


class TestDataCollector(unittest.TestCase):
    """Test cases for DataCollector."""
    
    def setUp(self):
        self.collector = DataCollector()
    
    def test_fetch_stock_data(self):
        """Test fetching stock data."""
        # Test with a reliable stock
        data = self.collector.fetch_stock_data('AAPL', period='1mo')
        
        if data is not None:
            self.assertIsInstance(data, pd.DataFrame)
            self.assertGreater(len(data), 0)
            self.assertIn('Close', data.columns)
            self.assertIn('Volume', data.columns)
    
    def test_fetch_company_info(self):
        """Test fetching company information."""
        info = self.collector.fetch_company_info('AAPL')
        
        if info is not None:
            self.assertIsInstance(info, dict)
            self.assertIn('symbol', info)
            self.assertEqual(info['symbol'], 'AAPL')


class TestDataPreprocessor(unittest.TestCase):
    """Test cases for DataPreprocessor."""
    
    def setUp(self):
        self.preprocessor = DataPreprocessor()
        # Create sample data
        dates = pd.date_range('2023-01-01', periods=100, freq='D')
        self.sample_data = pd.DataFrame({
            'Open': np.random.uniform(100, 150, 100),
            'High': np.random.uniform(100, 160, 100),
            'Low': np.random.uniform(90, 140, 100),
            'Close': np.random.uniform(100, 150, 100),
            'Volume': np.random.randint(1000000, 10000000, 100)
        }, index=dates)
    
    def test_clean_stock_data(self):
        """Test data cleaning."""
        cleaned_data = self.preprocessor.clean_stock_data(self.sample_data)
        
        self.assertIsInstance(cleaned_data, pd.DataFrame)
        self.assertEqual(len(cleaned_data), len(self.sample_data))
        self.assertFalse(cleaned_data.isnull().any().any())
    
    def test_add_basic_features(self):
        """Test adding basic features."""
        features_data = self.preprocessor.add_basic_features(self.sample_data)
        
        self.assertIn('Price_Range', features_data.columns)
        self.assertIn('Daily_Return', features_data.columns)
        self.assertIn('Volatility_5d', features_data.columns)
    
    def test_create_target_variable(self):
        """Test creating target variables."""
        target_data = self.preprocessor.create_target_variable(self.sample_data)
        
        self.assertIn('Target_Up', target_data.columns)
        self.assertIn('Future_Return', target_data.columns)


class TestTechnicalAnalyzer(unittest.TestCase):
    """Test cases for TechnicalAnalyzer."""
    
    def setUp(self):
        self.analyzer = TechnicalAnalyzer()
        # Create sample data
        dates = pd.date_range('2023-01-01', periods=100, freq='D')
        np.random.seed(42)  # For reproducible results
        
        prices = 100 + np.cumsum(np.random.randn(100) * 0.5)
        self.sample_data = pd.DataFrame({
            'Open': prices + np.random.randn(100) * 0.1,
            'High': prices + np.abs(np.random.randn(100) * 0.5),
            'Low': prices - np.abs(np.random.randn(100) * 0.5),
            'Close': prices,
            'Volume': np.random.randint(1000000, 10000000, 100)
        }, index=dates)
    
    def test_calculate_rsi(self):
        """Test RSI calculation."""
        rsi = self.analyzer.calculate_rsi(self.sample_data)
        
        self.assertIsInstance(rsi, pd.Series)
        self.assertTrue(all(0 <= val <= 100 for val in rsi.dropna()))
    
    def test_calculate_macd(self):
        """Test MACD calculation."""
        macd_dict = self.analyzer.calculate_macd(self.sample_data)
        
        self.assertIn('MACD', macd_dict)
        self.assertIn('MACD_Signal', macd_dict)
        self.assertIn('MACD_Histogram', macd_dict)
        
        for key, series in macd_dict.items():
            self.assertIsInstance(series, pd.Series)
    
    def test_calculate_bollinger_bands(self):
        """Test Bollinger Bands calculation."""
        bb_dict = self.analyzer.calculate_bollinger_bands(self.sample_data)
        
        self.assertIn('BB_Upper', bb_dict)
        self.assertIn('BB_Middle', bb_dict)
        self.assertIn('BB_Lower', bb_dict)
        
        # Test that upper > middle > lower
        valid_indices = ~(bb_dict['BB_Upper'].isna() | bb_dict['BB_Middle'].isna() | bb_dict['BB_Lower'].isna())
        if valid_indices.any():
            self.assertTrue(all(bb_dict['BB_Upper'][valid_indices] >= bb_dict['BB_Middle'][valid_indices]))
            self.assertTrue(all(bb_dict['BB_Middle'][valid_indices] >= bb_dict['BB_Lower'][valid_indices]))


class TestHelpers(unittest.TestCase):
    """Test cases for utility functions."""
    
    def test_calculate_percentage_change(self):
        """Test percentage change calculation."""
        result = helpers.calculate_percentage_change(100, 110)
        self.assertEqual(result, 10.0)
        
        result = helpers.calculate_percentage_change(100, 90)
        self.assertEqual(result, -10.0)
        
        result = helpers.calculate_percentage_change(0, 10)
        self.assertEqual(result, 0.0)
    
    def test_format_currency(self):
        """Test currency formatting."""
        result = helpers.format_currency(1234.56)
        self.assertEqual(result, "$1,234.56")
        
        result = helpers.format_currency(1234.56, "EUR")
        self.assertEqual(result, "1,234.56 EUR")
    
    def test_format_large_number(self):
        """Test large number formatting."""
        self.assertEqual(helpers.format_large_number(1234), "1.2K")
        self.assertEqual(helpers.format_large_number(1234567), "1.2M")
        self.assertEqual(helpers.format_large_number(1234567890), "1.2B")
    
    def test_safe_divide(self):
        """Test safe division."""
        self.assertEqual(helpers.safe_divide(10, 2), 5.0)
        self.assertEqual(helpers.safe_divide(10, 0), 0.0)
        self.assertEqual(helpers.safe_divide(10, 0, -1), -1)
    
    def test_normalize_score(self):
        """Test score normalization."""
        result = helpers.normalize_score(50, 0, 100)
        self.assertEqual(result, 50.0)
        
        result = helpers.normalize_score(25, 0, 100)
        self.assertEqual(result, 25.0)
        
        result = helpers.normalize_score(150, 0, 100)
        self.assertEqual(result, 100.0)  # Clamped to max
    
    def test_validate_symbols(self):
        """Test symbol validation."""
        symbols = ['AAPL', 'msft', 'GOOGL123', '', 'TSL@']
        valid = helpers.validate_symbols(symbols)
        
        self.assertIn('AAPL', valid)
        self.assertIn('MSFT', valid)
        self.assertNotIn('GOOGL123', valid)  # Too long
        self.assertNotIn('', valid)  # Empty
        self.assertNotIn('TSL@', valid)  # Invalid character


class TestIntegration(unittest.TestCase):
    """Integration tests for the complete system."""
    
    def test_basic_workflow(self):
        """Test a basic analysis workflow."""
        try:
            # Initialize components
            collector = DataCollector()
            preprocessor = DataPreprocessor()
            analyzer = TechnicalAnalyzer()
            
            # Fetch sample data
            data = collector.fetch_stock_data('AAPL', period='1mo')
            
            if data is not None and not data.empty:
                # Clean and preprocess
                clean_data = preprocessor.clean_stock_data(data)
                feature_data = preprocessor.add_basic_features(clean_data)
                
                # Add technical indicators
                technical_data = analyzer.calculate_all_indicators(feature_data)
                
                # Verify we have additional columns
                self.assertGreater(len(technical_data.columns), len(data.columns))
                
                # Check for key indicators
                self.assertIn('RSI', technical_data.columns)
                self.assertIn('MACD', technical_data.columns)
                
                print("✅ Integration test passed - basic workflow completed successfully")
            else:
                print("⚠️ Integration test skipped - no data available")
                
        except Exception as e:
            self.fail(f"Integration test failed: {str(e)}")


if __name__ == '__main__':
    # Set up test environment
    print("🧪 Running Stock Prediction System Tests")
    print("=" * 50)
    
    # Create necessary directories
    os.makedirs('logs', exist_ok=True)
    os.makedirs('data', exist_ok=True)
    
    # Run tests
    unittest.main(verbosity=2)