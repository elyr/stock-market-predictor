"""
Component scores (technical, momentum, volume), shown as explanations, and their plain-language signals.

Part of :class:`src.prediction.stock_ranker.StockRanker`; methods use the state
set up in its ``__init__`` (config, data collector, predictors).
"""

import logging
from typing import Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def recommendation_label(score: float, confidence: float) -> str:
    """
    Map a composite score and ML confidence to a recommendation label.

    Args:
        score: Composite score (0-100)
        confidence: ML model agreement (0-1)

    Returns:
        One of 'STRONG BUY', 'BUY', 'HOLD/WATCH', 'AVOID'
    """
    if score >= 75 and confidence >= 0.7:
        return "STRONG BUY"
    if score >= 65 and confidence >= 0.6:
        return "BUY"
    if score >= 55:
        return "HOLD/WATCH"
    return "AVOID"


def composite_score(scores: Dict[str, float], weights: Dict[str, float]) -> float:
    """
    Weighted average of the available component scores.

    Weights are renormalised over the components present, so leaving one out
    (e.g. the model score before it is trained) does not drag the composite towards zero.
    """
    used = {k: w for k, w in weights.items() if k in scores and scores[k] is not None and w > 0}
    total = sum(used.values())
    if total == 0:
        return 50.0
    return sum(scores[k] * w for k, w in used.items()) / total


def percentile_scores(values: pd.Series) -> pd.Series:
    """Map values to 0-100 by cross-sectional rank (best = 100)."""
    if len(values) < 2:
        return pd.Series(50.0, index=values.index)
    return (values.rank(method='average') - 1) / (len(values) - 1) * 100


DEFAULT_WEIGHTS = {
    'technical_score': 0.25,
    'ml_prediction': 0.35,
    'momentum_score': 0.20,
    'volume_score': 0.10,
}


# Scores that are computed from price/volume history alone (usable in backtests)
PRICE_BASED_COMPONENTS = ('technical_score', 'momentum_score', 'volume_score')


class ScoringMixin:
    """Component scores (technical, momentum, volume), shown as explanations, and their plain-language signals."""

    def calculate_technical_score(self, data: pd.DataFrame, patterns: Dict[str, bool] = None) -> float:
        """
        Calculate technical analysis score (0-100) from the latest row.

        Args:
            data: Prepared data
            patterns: Chart patterns for the latest window; read from the
                ``Pattern_*`` columns of the latest row when not given
        """
        if data.empty:
            return 0.0

        latest = data.iloc[-1]
        score_components = []

        try:
            rsi = latest.get('RSI', np.nan)
            if pd.notna(rsi):
                score_components.append(90 if rsi < 30 else 70 if rsi < 50 else 50 if rsi < 70 else 20)

            if pd.notna(latest.get('MACD', np.nan)) and pd.notna(latest.get('MACD_Signal', np.nan)):
                macd_score = 80 if latest['MACD'] > latest['MACD_Signal'] else 20
                if latest.get('MACD_Cross_Up', 0):
                    macd_score += 20
                score_components.append(min(macd_score, 100))

            bb_position = latest.get('BB_Position', np.nan)
            if pd.notna(bb_position):
                score_components.append(90 if bb_position < 0.2 else 70 if bb_position < 0.5
                                        else 50 if bb_position < 0.8 else 20)

            sma_scores = [80 if latest[f'Price_Above_SMA_{p}'] else 20
                          for p in (20, 50)
                          if f'Price_Above_SMA_{p}' in latest and pd.notna(latest.get(f'SMA_{p}', np.nan))]
            if sma_scores:
                score_components.append(np.mean(sma_scores))

            volume_ratio = latest.get('Volume_Ratio', np.nan)
            if pd.notna(volume_ratio):
                score_components.append(80 if volume_ratio > 1.5 else 60 if volume_ratio > 1.0 else 30)

            if patterns is None:
                patterns = {c[len('Pattern_'):]: bool(latest[c]) for c in data.columns if c.startswith('Pattern_')}
            bullish = ('bullish_flag', 'double_bottom', 'ascending_triangle')
            bearish = ('double_top', 'head_and_shoulders', 'descending_triangle')
            if any(patterns.get(p) for p in bullish):
                score_components.append(80)
            elif any(patterns.get(p) for p in bearish):
                score_components.append(30)
            else:
                score_components.append(50)

        except Exception as e:
            logger.warning(f"Error calculating technical score: {str(e)}")

        return float(np.mean(score_components)) if score_components else 50.0

    def calculate_momentum_score(self, data: pd.DataFrame) -> float:
        """
        Momentum score (0-100): a weighted average of rate-of-change across
        horizons, volatility and up-day streaks, normalised to stay within 0-100.
        """
        if len(data) < 20:
            return 50.0

        latest = data.iloc[-1]
        weighted = []  # (score, weight)

        try:
            roc_weights = {'1d': 0.4, '5d': 0.3, '10d': 0.2, '20d': 0.1}
            for period, weight in roc_weights.items():
                roc = latest.get(f'ROC_{period}', np.nan)
                if pd.isna(roc):
                    continue
                if period == '1d':
                    score = 90 if roc > 2 else 70 if roc > 0.5 else 60 if roc > 0 else 40 if roc > -0.5 else 20
                else:
                    score = 80 if roc > 5 else 60 if roc > 2 else 50 if roc > 0 else 30
                weighted.append((score, weight))

            vol = latest.get('Volatility_20d', np.nan)
            if pd.notna(vol):
                score = 80 if vol < 0.02 else 60 if vol < 0.04 else 40 if vol < 0.06 else 20
                weighted.append((score, 0.2))

            streak = [min(60 + d * 5, 90) for d in (2, 3, 4, 5) if latest.get(f'Consecutive_Up_{d}d', 0)]
            weighted.append((max(streak) if streak else 50, 0.3))

        except Exception as e:
            logger.warning(f"Error calculating momentum score: {str(e)}")

        total_weight = sum(w for _, w in weighted)
        if total_weight == 0:
            return 50.0
        return float(sum(s * w for s, w in weighted) / total_weight)

    def calculate_volume_score(self, data: pd.DataFrame) -> float:
        """Volume-based score (0-100)."""
        if len(data) < 20:
            return 50.0

        latest = data.iloc[-1]
        recent_data = data.tail(5)
        score_components = []

        try:
            volume_ratio = latest.get('Volume_Ratio', np.nan)
            if pd.notna(volume_ratio):
                score_components.append(90 if volume_ratio > 2.0 else 80 if volume_ratio > 1.5
                                        else 60 if volume_ratio > 1.0 else 40 if volume_ratio > 0.7 else 20)

            avg_volume = recent_data['Volume'].mean()
            if avg_volume > 0:
                slope = np.polyfit(range(len(recent_data)), recent_data['Volume'].values, 1)[0] / avg_volume
                score_components.append(80 if slope > 0.1 else 60 if slope > 0 else 40 if slope > -0.1 else 20)

            price_changes = recent_data['Close'].pct_change().dropna()
            volume_changes = recent_data['Volume'].pct_change().dropna()
            if len(price_changes) >= 3 and price_changes.std() > 0 and volume_changes.std() > 0:
                correlation = np.corrcoef(price_changes, volume_changes)[0, 1]
                if not np.isnan(correlation):
                    score_components.append(80 if correlation > 0.3 else 60 if correlation > 0
                                            else 40 if correlation > -0.3 else 20)

            if 'OBV' in data.columns and len(data) >= 10:
                obv_recent = data['OBV'].tail(10).fillna(0).values
                obv_trend = np.polyfit(range(len(obv_recent)), obv_recent, 1)[0]
                score_components.append(70 if obv_trend > 0 else 30)

        except Exception as e:
            logger.warning(f"Error calculating volume score: {str(e)}")

        return float(np.mean(score_components)) if score_components else 50.0

    def score_components(self, data: pd.DataFrame, patterns: Dict[str, bool] = None) -> Dict[str, float]:
        """Price-based component scores (technical, momentum, volume) for the latest row."""
        return {
            'technical_score': self.calculate_technical_score(data, patterns),
            'momentum_score': self.calculate_momentum_score(data),
            'volume_score': self.calculate_volume_score(data),
        }

    def describe_signals(self, data: pd.DataFrame) -> List[str]:
        """Plain-language notes on the notable signals in the latest row."""
        latest = data.iloc[-1]
        notes = []
        rsi = latest.get('RSI', np.nan)
        if pd.notna(rsi):
            if rsi < 30:
                notes.append(f"RSI {rsi:.0f}: oversold")
            elif rsi > 70:
                notes.append(f"RSI {rsi:.0f}: overbought")
        if latest.get('MACD_Cross_Up', 0):
            notes.append("MACD just crossed above its signal line")
        elif latest.get('MACD_Cross_Down', 0):
            notes.append("MACD just crossed below its signal line")
        bb = latest.get('BB_Position', np.nan)
        if pd.notna(bb) and bb < 0.1:
            notes.append("Trading near the lower Bollinger band")
        elif pd.notna(bb) and bb > 0.9:
            notes.append("Trading near the upper Bollinger band")
        volume_ratio = latest.get('Volume_Ratio', np.nan)
        if pd.notna(volume_ratio) and volume_ratio > 1.8:
            notes.append(f"Volume {volume_ratio:.1f}x its 20-day average")
        for period in (50, 200):
            distance = latest.get(f'Price_Distance_SMA_{period}', np.nan)
            if pd.notna(distance) and pd.notna(latest.get(f'SMA_{period}', np.nan)):
                side = 'above' if distance > 0 else 'below'
                if abs(distance) > 0.1:
                    notes.append(f"{abs(distance):.0%} {side} its {period}-day average")
        roc5 = latest.get('ROC_5d', np.nan)
        if pd.notna(roc5) and abs(roc5) > 8:
            notes.append(f"{roc5:+.1f}% over the last 5 days")
        for pattern in ('double_bottom', 'bullish_flag', 'ascending_triangle', 'double_top',
                        'head_and_shoulders', 'descending_triangle'):
            if latest.get(f'Pattern_{pattern}', False):
                notes.append(f"Chart pattern: {pattern.replace('_', ' ')}")
        return notes
