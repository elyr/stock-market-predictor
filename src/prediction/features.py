"""
Data preparation: indicators, features and targets for each asset and for the universe.

Part of :class:`src.prediction.asset_ranker.AssetRanker`; methods use the state
set up in its ``__init__`` (config, data collector, predictors).
"""

import logging
from typing import Dict, List

import pandas as pd

from src.data.preprocessor import add_relative_targets
from src.models.cross_section import add_cross_section_features
from src.models.volatility import add_market_volatility

logger = logging.getLogger(__name__)


class FeaturesMixin:
    """Data preparation: indicators, features and targets for each asset and for the universe."""

    def prepare_symbol_data(self, raw: pd.DataFrame) -> pd.DataFrame:
        """
        Run the per-asset feature pipeline on raw OHLCV data.

        Every feature at date t uses only data up to t. The targets look
        ``horizon`` days ahead and are NaN where the future is unknown.
        """
        data = self.preprocessor.clean_price_data(raw)
        data = self.preprocessor.add_basic_features(data)
        data = self.preprocessor.add_moving_averages(data)
        data = self.preprocessor.add_momentum_features(data)
        data = self.preprocessor.add_pattern_features(data)
        data = self.preprocessor.add_support_resistance(data)
        data = self.technical_analyzer.calculate_all_indicators(data)
        data = self.preprocessor.create_target_variable(data, horizon=self.horizon,
                                                        threshold=self.target_threshold)
        data = self.preprocessor.add_volatility_targets(data, horizon=self.volatility.horizon)
        return data

    def add_universe_features(self, prepared: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """Asset-class-specific cross-sectional features. Overridden by subclasses."""
        return prepared

    def prepare_universe(self, raw_data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """
        Prepare every asset, then add features and targets that need the whole universe
        (relative returns, market volatility, asset-class features).
        """
        prepared = {}
        for symbol, data in raw_data.items():
            try:
                if data is None or data.empty:
                    logger.warning(f"No data available for {symbol}")
                    continue
                prepared[symbol] = self.prepare_symbol_data(data)
            except Exception as e:
                logger.error(f"Error preparing data for {symbol}: {str(e)}")
        prepared = add_relative_targets(prepared)
        prepared = add_market_volatility(prepared)
        prepared = self.add_universe_features(prepared)
        if self.model_kind == 'cross_section':
            prepared = add_cross_section_features(prepared, horizon=self.horizon, market=self.market_symbol,
                                                  momentum=self.momentum_style, year=self.periods_per_year,
                                                  long_horizon=self.long_horizon)
        return prepared

    def fetch_and_prepare_data(self, symbols: List[str], period: str = None) -> Dict[str, pd.DataFrame]:
        """
        Fetch and prepare data for all symbols.

        Args:
            symbols: Asset symbols
            period: History to fetch (defaults to the universe's timeframe)
        """
        logger.info(f"Fetching data for {len(symbols)} symbols...")
        period = period or self.universe_config.get('timeframe', '2y')
        raw_data = self.data_collector.fetch_many_prices(symbols, period=period)
        prepared = self.prepare_universe(raw_data)
        logger.info(f"Successfully prepared data for {len(prepared)} symbols")
        return prepared
