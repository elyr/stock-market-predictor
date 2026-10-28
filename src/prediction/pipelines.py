"""
Asset-class pipelines.

Stocks and crypto are ranked by separate pipeline instances: each has its own
symbols, filters, features, trained models and saved model file, so nothing
learned on one asset class leaks into the other.

* ``StockPipeline`` adds features relative to the stock universe (how a stock's
  recent return compares with the average stock) and uses sectors to diversify.
* ``CryptoPipeline`` adds features relative to Bitcoin, which drives most of
  the crypto market (return vs BTC, rolling beta and correlation to BTC),
  groups coins by category, and annualizes over 365 days.
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.data.collector import DataCollector
from src.prediction.stock_ranker import StockRanker

UNIVERSES = ('stocks', 'crypto')

CRYPTO_CATEGORIES = {
    'BTC': ('Bitcoin', 'Store of value'),
    'ETH': ('Ethereum', 'Smart-contract platform'),
    'BNB': ('BNB', 'Exchange token'),
    'SOL': ('Solana', 'Smart-contract platform'),
    'XRP': ('XRP', 'Payments'),
    'ADA': ('Cardano', 'Smart-contract platform'),
    'DOGE': ('Dogecoin', 'Meme'),
    'TRX': ('TRON', 'Smart-contract platform'),
    'AVAX': ('Avalanche', 'Smart-contract platform'),
    'LINK': ('Chainlink', 'Oracle'),
    'DOT': ('Polkadot', 'Interoperability'),
    'LTC': ('Litecoin', 'Payments'),
    'BCH': ('Bitcoin Cash', 'Payments'),
    'XLM': ('Stellar', 'Payments'),
    'ATOM': ('Cosmos', 'Interoperability'),
    'ETC': ('Ethereum Classic', 'Smart-contract platform'),
    'HBAR': ('Hedera', 'Smart-contract platform'),
    'FIL': ('Filecoin', 'Storage'),
    'NEAR': ('NEAR Protocol', 'Smart-contract platform'),
    'ICP': ('Internet Computer', 'Smart-contract platform'),
    'AAVE': ('Aave', 'DeFi'),
    'ALGO': ('Algorand', 'Smart-contract platform'),
}


def _cross_section(prepared: Dict[str, pd.DataFrame], column: str) -> pd.DataFrame:
    return pd.concat({s: d[column] for s, d in prepared.items() if column in d}, axis=1)


class StockPipeline(StockRanker):
    """US equities: universe-relative momentum features and sector diversification."""

    asset_class = 'stocks'

    def add_universe_features(self, prepared: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        if len(prepared) < 2:
            return prepared
        roc5, roc20 = _cross_section(prepared, 'ROC_5d'), _cross_section(prepared, 'ROC_20d')
        rank20 = roc20.rank(axis=1, pct=True)
        result = {}
        for symbol, data in prepared.items():
            df = data.copy()
            df['ROC_5d_vs_Universe'] = df['ROC_5d'] - roc5.mean(axis=1).reindex(df.index)
            df['ROC_20d_vs_Universe'] = df['ROC_20d'] - roc20.mean(axis=1).reindex(df.index)
            df['ROC_20d_Rank'] = rank20[symbol].reindex(df.index)
            result[symbol] = df
        return result


class CryptoPipeline(StockRanker):
    """Crypto: Bitcoin-relative features, coin categories, 7-day calendar."""

    asset_class = 'crypto'
    benchmark = 'BTC-USD'

    def add_universe_features(self, prepared: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        if not prepared:
            return prepared
        returns = _cross_section(prepared, 'Daily_Return')
        if self.benchmark in returns:
            btc = returns[self.benchmark]
            btc_roc5 = prepared[self.benchmark]['ROC_5d']
            btc_roc20 = prepared[self.benchmark]['ROC_20d']
        else:  # fall back to the universe average when BTC is not in the list
            btc = returns.mean(axis=1)
            btc_roc5 = _cross_section(prepared, 'ROC_5d').mean(axis=1)
            btc_roc20 = _cross_section(prepared, 'ROC_20d').mean(axis=1)

        result = {}
        for symbol, data in prepared.items():
            df = data.copy()
            r = df['Daily_Return']
            b = btc.reindex(df.index)
            cov = r.rolling(30).cov(b)
            var = b.rolling(30).var()
            df['Beta_BTC_30d'] = cov / var.replace(0, np.nan)
            df['Corr_BTC_30d'] = r.rolling(30).corr(b)
            df['ROC_5d_vs_BTC'] = df['ROC_5d'] - btc_roc5.reindex(df.index)
            df['ROC_20d_vs_BTC'] = df['ROC_20d'] - btc_roc20.reindex(df.index)
            df['BTC_ROC_5d'] = btc_roc5.reindex(df.index)
            result[symbol] = df
        return result

    def asset_metadata(self, symbol: str, company_info: Optional[Dict]) -> Dict[str, str]:
        ticker = symbol.split('-')[0]
        name, category = CRYPTO_CATEGORIES.get(ticker, (None, 'Other'))
        info = company_info or {}
        display = info.get('name')
        if not display or display in ('N/A', symbol) or 'synthetic' in str(display):
            display = name or ticker
        return {'name': display, 'sector': category}

    def describe_signals(self, data: pd.DataFrame) -> List[str]:
        notes = super().describe_signals(data)
        latest = data.iloc[-1]
        beta = latest.get('Beta_BTC_30d', np.nan)
        if pd.notna(beta) and abs(beta - 1) > 0.4 and latest.get('Corr_BTC_30d', 0) > 0.3:
            notes.append(f"Moves {beta:.1f}x Bitcoin (30-day beta)")
        rel = latest.get('ROC_20d_vs_BTC', np.nan)
        if pd.notna(rel) and abs(rel) > 15:
            notes.append(f"{rel:+.0f} pts vs Bitcoin over 20 days")
        return notes

    def _get_market_sentiment_summary(self) -> str:
        data = self.last_prepared.get(self.benchmark)
        if data is None or data.empty:
            return "Neutral"
        change = data['Daily_Return'].iloc[-1] * 100
        return "Bullish" if change > 3 else "Positive" if change > 0 else "Negative" if change > -3 else "Bearish"


PIPELINES = {'stocks': StockPipeline, 'crypto': CryptoPipeline}


def create_pipeline(universe: str = 'stocks', config_path: str = "config/config.yaml",
                    data_collector: Optional[DataCollector] = None,
                    config_overrides: Optional[dict] = None) -> StockRanker:
    """
    Build the pipeline for an asset class.

    Args:
        universe: 'stocks' or 'crypto'
        config_path: config file
        data_collector: optional data source (defaults to live Yahoo Finance)
        config_overrides: dotted-path settings applied over the config file
    """
    if universe not in PIPELINES:
        raise ValueError(f"Unknown universe '{universe}'; expected one of {', '.join(UNIVERSES)}")
    return PIPELINES[universe](config_path, data_collector=data_collector, universe=universe,
                               config_overrides=config_overrides)
