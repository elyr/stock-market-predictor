# 🚀 Stock Market Prediction System

An advanced AI-powered stock market prediction system that analyzes market indicators, technical patterns, and sentiment to identify the top 10 stocks most likely to move up the next trading day.

## 🌟 Features

- **🤖 Machine Learning Models**: Random Forest, XGBoost, Neural Networks, and LSTM models
- **📊 Technical Analysis**: 20+ technical indicators including RSI, MACD, Bollinger Bands, ADX, and more
- **📈 Pattern Recognition**: Identifies chart patterns like double tops, head & shoulders, triangles, flags
- **💭 Sentiment Analysis**: Analyzes news sentiment, market breadth, and fear/greed indicators
- **🎯 Smart Ranking**: Multi-factor scoring algorithm with configurable weights
- **🖥️ Multiple Interfaces**: Command-line interface and web dashboard
- **📱 Real-time Data**: Fetches live market data from Yahoo Finance and Alpha Vantage APIs
- **📊 Comprehensive Reports**: Detailed analysis with confidence scores and trading recommendations

## 🏗️ Project Structure

```
automatic prediction/
├── .github/
│   └── copilot-instructions.md    # Development guidelines
├── config/
│   └── config.yaml               # Configuration settings
├── data/                         # Output data and cache
├── logs/                         # Application logs
├── src/
│   ├── data/
│   │   ├── collector.py          # Data fetching from APIs
│   │   ├── preprocessor.py       # Data cleaning and feature engineering
│   │   └── __init__.py
│   ├── analysis/
│   │   ├── technical_indicators.py  # Technical analysis
│   │   ├── sentiment_analysis.py    # Sentiment analysis
│   │   └── __init__.py
│   ├── models/
│   │   ├── ml_models.py          # Machine learning models
│   │   ├── evaluation.py         # Model evaluation utilities
│   │   └── __init__.py
│   ├── prediction/
│   │   ├── stock_ranker.py       # Main ranking system
│   │   └── __init__.py
│   ├── utils/                    # Utility functions
│   └── cli.py                    # Command-line interface
├── web/
│   └── dashboard.py              # Web dashboard
├── tests/                        # Unit tests
├── main.py                       # Main entry point
├── run_dashboard.py              # Web dashboard launcher
├── requirements.txt              # Python dependencies
├── .env.template                 # Environment variables template
└── README.md                     # This file
```

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <repository-url>
cd "automatic prediction"

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # On Windows
# source venv/bin/activate  # On macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

```bash
# Copy environment template
copy .env.template .env  # On Windows
# cp .env.template .env  # On macOS/Linux

# Edit .env file with your API keys (optional)
# ALPHA_VANTAGE_API_KEY=your_api_key_here
```

### 3. Run Analysis

**Quick Start - Simple Analysis:**

```bash
python main.py
```

**Expected Output:**

```
🚀 Stock Market Prediction System
==================================================
Initializing system...
Analyzing 10 stocks...
This may take a few minutes...

🏆 TOP 10 STOCK RECOMMENDATIONS
================================================================================
Rank Symbol   Company                        Score  Price    Change%
--------------------------------------------------------------------------------
1    AAPL     Apple Inc.                     70.8   $262.24  3.9    %
2    GOOGL    Alphabet Inc.                  62.8   $256.55  1.3    %
3    MSFT     Microsoft Corporation          58.0   $516.79  0.6    %
...
```

**Web Dashboard:**

```bash
python run_dashboard.py
# Open browser to http://127.0.0.1:8050
```

## 📊 Usage Examples

### Command Line Interface

```bash
# Analyze default stocks (main entry point)
python main.py

# Command line interface (if you want specific commands)
python src/cli.py analyze

# Analyze specific stocks
python src/cli.py analyze --symbols "AAPL,MSFT,GOOGL,AMZN,TSLA" --top-n 10

# Get detailed analysis for single stock
python src/cli.py single --symbol AAPL

# Check market overview
python src/cli.py market

# View configuration
python src/cli.py config
```

### Web Dashboard

```bash
# Launch web dashboard (recommended)
python run_dashboard.py

# Then open browser to http://127.0.0.1:8050
```

### Python API

```python
from src.prediction import StockRanker

# Initialize ranker
ranker = StockRanker()

# Get top 10 recommendations
symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']
recommendations = ranker.get_top_10_recommendations(symbols)

# Access results
top_10 = recommendations['top_10']
summary = recommendations['analysis_summary']

print(f"Best pick: {top_10.iloc[0]['Symbol']} with score {top_10.iloc[0]['Composite_Score']:.1f}")
```

## 🧠 How It Works

### 1. Data Collection

- Fetches real-time stock data from Yahoo Finance
- Optional Alpha Vantage API for additional market data
- Collects OHLCV data, company fundamentals, news, and market indicators

### 2. Technical Analysis

- **Trend Indicators**: RSI, MACD, Bollinger Bands, Moving Averages
- **Momentum Indicators**: ROC, Williams %R, Stochastic Oscillator
- **Volume Indicators**: OBV, Money Flow Index, Volume Analysis
- **Volatility Indicators**: ATR, Bollinger Band Width
- **Pattern Recognition**: Chart patterns and candlestick patterns

### 3. Machine Learning

- **Random Forest**: Ensemble learning for robust predictions
- **XGBoost**: Gradient boosting for high accuracy
- **Neural Networks**: Deep learning for complex patterns
- **LSTM**: Time series analysis for sequential patterns

### 4. Sentiment Analysis

- News sentiment using natural language processing
- Market breadth analysis (advance/decline ratios)
- Fear & greed index calculation
- Sector rotation analysis

### 5. Ranking Algorithm

Composite score calculation with configurable weights:

- Technical Score (30%): Technical indicator signals
- ML Prediction (25%): Machine learning probability
- Momentum Score (20%): Price and volume momentum
- Volume Score (15%): Volume analysis and confirmation
- Sentiment Score (10%): Market and stock-specific sentiment

## ⚙️ Configuration

Edit `config/config.yaml` to customize:

```yaml
# Stock symbols to analyze
stock_config:
  symbols: [AAPL, MSFT, GOOGL, ...] # Add your preferred stocks
  timeframe: "6mo" # Data timeframe
  interval: "1d" # Data interval

# Ranking weights
ranking_config:
  weights:
    technical_score: 0.30
    ml_prediction: 0.25
    momentum_score: 0.20
    volume_score: 0.15
    sentiment_score: 0.10

  # Stock filters
  filters:
    min_price: 5.0 # Minimum stock price
    min_volume: 1000000 # Minimum daily volume
    exclude_penny_stocks: true

# Technical indicator parameters
technical_analysis:
  rsi:
    period: 14
    overbought: 70
    oversold: 30
  # ... more indicators
```

## � Output

The system provides:

1. **Top 10 Ranked Stocks** with composite scores (0-100 scale)
2. **Detailed Analysis** for each stock including:
   - Technical indicator values and signals
   - ML prediction confidence scores
   - Price and volume metrics
   - Sector and fundamental data
   - Sentiment analysis from news and market data
3. **Trading Recommendations** (Strong Buy, Buy, Hold, Avoid)
4. **Market Overview** with major indices and sentiment indicators
5. **Exportable Reports** in CSV format with timestamps

**Current System Status:**

- ✅ Real-time data fetching working
- ✅ Technical analysis engine operational
- ✅ Basic ML models training (some refinement needed)
- ✅ Sentiment analysis functional
- ✅ Web dashboard operational
- ✅ CSV export working
- ⚠️ Some ML model errors (system falls back gracefully)
- ⚠️ Some technical indicators need fine-tuning

## 📊 Web Dashboard Features

- **Interactive Stock Analysis**: Enter symbols and get instant recommendations
- **Visual Charts**: Score breakdowns and sector distribution
- **Market Overview**: Real-time market indices and sentiment
- **Detailed Stock Cards**: In-depth analysis for top picks
- **Responsive Design**: Works on desktop and mobile devices

## 🔧 Advanced Features

### Custom Models

Add your own ML models by extending the `StockPredictor` class:

```python
from src.models import StockPredictor

class CustomPredictor(StockPredictor):
    def train_custom_model(self, X_train, y_train):
        # Implement your custom model
        pass
```

### Custom Indicators

Add technical indicators in `technical_indicators.py`:

```python
def calculate_custom_indicator(self, data: pd.DataFrame) -> pd.Series:
    # Implement your custom indicator
    return custom_values
```

### Backtesting

Evaluate model performance with historical data:

```python
from src.models import ModelEvaluator

evaluator = ModelEvaluator()
backtest_results = evaluator.backtest_model(
    data, model, feature_columns,
    start_date='2023-01-01',
    rebalance_frequency='monthly'
)
```

## 🚨 Disclaimers & Risk Warning

⚠️ **IMPORTANT**: This tool is for educational and research purposes only.

- **Not Financial Advice**: This system does not provide investment advice
- **Past Performance**: Historical data does not guarantee future results
- **Market Risk**: All investments carry risk of loss
- **Do Your Research**: Always conduct additional research before trading
- **Consult Professionals**: Consider consulting financial advisors
- **Paper Trading**: Test strategies with paper trading before using real money

## 🛠️ Development

### Running Tests

```bash
python -m pytest tests/
```

### Adding New Features

1. Follow the modular structure in `src/`
2. Add tests in `tests/`
3. Update configuration in `config/config.yaml`
4. Update documentation

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 🐛 Troubleshooting

### Common Issues

**Import Errors:**

- If you get `ModuleNotFoundError`, ensure you're running from the project root directory
- Use `python main.py` for simple analysis
- Use `python run_dashboard.py` for web interface
- Make sure all dependencies are installed: `pip install -r requirements.txt`

**Missing Dependencies:**

```bash
# Install required packages
pip install numpy pandas scikit-learn yfinance alpha-vantage
pip install matplotlib seaborn plotly dash dash-bootstrap-components
pip install xgboost tensorflow ta beautifulsoup4 python-dotenv
pip install schedule click rich joblib PyYAML textblob TA-Lib
```

**API Errors:**

- Alpha Vantage API key is optional - the system works with Yahoo Finance only
- If you get rate limit errors, the system will automatically retry
- Check your internet connection for data fetching issues

**Performance Issues:**

- Reduce the number of stocks analyzed if running slowly
- Disable debug mode in production
- Consider using a more powerful machine for large-scale analysis

### Environment Setup

**Windows:**

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**macOS/Linux:**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 📚 Dependencies

- **Data**: pandas, numpy, yfinance, alpha-vantage
- **ML**: scikit-learn, xgboost, tensorflow
- **Technical Analysis**: ta, talib (optional)
- **Visualization**: plotly, matplotlib, seaborn
- **Web**: dash, dash-bootstrap-components
- **CLI**: click, rich
- **Utilities**: requests, beautifulsoup4, python-dotenv

## 🔮 Future Enhancements

- [ ] Options flow analysis
- [ ] Crypto currency support
- [ ] Real-time alerts and notifications
- [ ] Portfolio optimization
- [ ] Backtesting with transaction costs
- [ ] Integration with trading platforms
- [ ] Mobile app
- [ ] Social sentiment analysis (Twitter, Reddit)
- [ ] Earnings calendar integration
- [ ] ESG scoring

## 📞 Support

For issues, questions, or contributions:

1. Check the documentation
2. Review configuration settings
3. Check logs in `logs/` directory
4. Submit an issue with detailed information

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

**Happy Trading! 📈**

Remember: The market is unpredictable, but good analysis helps make informed decisions. Always trade responsibly!
