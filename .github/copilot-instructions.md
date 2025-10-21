# Stock Market Prediction Project - Copilot Instructions

This is an advanced stock market prediction system that analyzes market indicators and technical patterns to identify the top 10 stocks most likely to move up the next trading day.

## Project Overview
- **Language**: Python 3.8+
- **Framework**: scikit-learn, pandas, numpy for ML and data analysis
- **Data Sources**: Yahoo Finance API, Alpha Vantage API, financial data providers
- **Features**: Technical analysis, machine learning predictions, real-time data fetching
- **Output**: Daily top 10 stock recommendations with confidence scores

## Key Components
1. **Data Collection**: Real-time stock prices, volume, market indicators
2. **Technical Analysis**: RSI, MACD, Bollinger Bands, moving averages, support/resistance
3. **Machine Learning**: Random Forest, XGBoost, LSTM models for price prediction
4. **Ranking System**: Multi-factor scoring algorithm combining technical and fundamental analysis
5. **User Interface**: CLI tool and optional web dashboard

## Development Guidelines
- Use type hints and docstrings for all functions
- Implement error handling for API failures and data issues
- Cache data to avoid API rate limits
- Use configuration files for API keys and parameters
- Follow PEP 8 style guidelines
- Create modular, testable code structure