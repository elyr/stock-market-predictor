"""
Price ranges for the next day and the next week, with a measured reliability.

A single "expected price" would mislead: over a day or a week the best point
estimate is almost exactly today's price, because the expected move is tiny
compared with the noise. What *can* be forecast is how far prices are likely
to move, so this module forecasts ranges.

Method (split conformal prediction on a volatility scale):

1. For each asset and date ``t``, an exponentially weighted volatility of
   daily log returns up to ``t`` (RiskMetrics, decay 0.94), blended with the
   asset's one-year volatility so a quiet week does not make it overconfident.
2. The move over the next ``h`` days, divided by ``sigma_t * sqrt(h)``, is a
   standardized move ``z``. Pooled across the universe, the empirical
   quantiles of ``z`` capture fat tails that a normal curve would miss.
3. A range is ``price_t * exp(q * sigma_t * sqrt(h))`` for the 5%, 25%, 75%
   and 95% quantiles ``q``, centred on today's price (the median move is set
   to zero: past drift is not a forecast).

Fitting splits the dates chronologically: quantiles from the earlier part,
coverage measured on the later part after a purge gap of ``h`` days, so the
reported reliability comes from dates the quantiles never saw. The final
quantiles are then refitted on everything. Every value at ``t`` uses only
prices up to ``t``.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

QUANTILES = (0.05, 0.25, 0.75, 0.95)
EWMA_DECAY = 0.94
LONG_WINDOW = 252
LONG_WEIGHT = 0.3
MIN_HISTORY = 60


def horizons_for(periods_per_year: int) -> Dict[str, int]:
    """Stocks: next session and 5 sessions. Crypto (trades every day): 24 hours and 7 days."""
    return {'day': 1, 'week': 7 if periods_per_year >= 360 else 5}


def horizon_labels(periods_per_year: int) -> Dict[str, str]:
    crypto = periods_per_year >= 360
    return {'day': 'Next 24 hours' if crypto else 'Next session',
            'week': 'Next 7 days' if crypto else 'Next 5 sessions'}


def daily_volatility(close: pd.Series) -> pd.Series:
    """Volatility of daily log returns known at each close (no future data)."""
    returns = np.log(close / close.shift(1))
    ewma = returns.pow(2).ewm(alpha=1 - EWMA_DECAY, adjust=False, min_periods=20).mean()
    long = returns.pow(2).rolling(LONG_WINDOW, min_periods=MIN_HISTORY).mean()
    variance = (1 - LONG_WEIGHT) * ewma + LONG_WEIGHT * long.fillna(ewma)
    return np.sqrt(variance)


def standardized_moves(closes: Dict[str, pd.Series], days: int) -> pd.DataFrame:
    """Every (date, symbol) with its standardized move over the next ``days`` rows."""
    frames = []
    for symbol, close in closes.items():
        close = close.dropna()
        if len(close) < MIN_HISTORY + days:
            continue
        sigma = daily_volatility(close)
        future = np.log(close.shift(-days) / close)
        z = future / (sigma * np.sqrt(days))
        frame = pd.DataFrame({'z': z, 'symbol': symbol}).dropna()
        frames.append(frame[np.isfinite(frame['z'])])
    if not frames:
        return pd.DataFrame(columns=['z', 'symbol'])
    return pd.concat(frames).sort_index(kind='stable')


def range_quantiles(z: np.ndarray) -> Dict[str, float]:
    """Quantiles of standardized moves, centred so the median move is zero."""
    z = z - np.median(z)
    return {f'q{int(q * 100):02d}': float(np.quantile(z, q)) for q in QUANTILES}


def coverage(z: np.ndarray, quantiles: Dict[str, float]) -> Dict[str, float]:
    inside50 = (z >= quantiles['q25']) & (z <= quantiles['q75'])
    inside90 = (z >= quantiles['q05']) & (z <= quantiles['q95'])
    return {'coverage_50': float(inside50.mean()), 'coverage_90': float(inside90.mean()), 'samples': int(len(z))}


@dataclass
class RangeForecaster:
    """Ranges for each horizon of one universe."""

    periods_per_year: int = 252
    test_fraction: float = 0.25
    horizons: Dict[str, int] = field(default_factory=dict)
    quantiles: Dict[str, Dict[str, float]] = field(default_factory=dict)
    evaluation: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def __post_init__(self):
        self.horizons = self.horizons or horizons_for(self.periods_per_year)

    def fit(self, closes: Dict[str, pd.Series]) -> Dict[str, Dict[str, float]]:
        """
        Measure coverage on held-out recent dates, then refit on everything.

        Returns:
            Per horizon: coverage of the 50% and 90% ranges on the held-out
            dates, the number of samples, and the typical width of the 90% range
        """
        for key, days in self.horizons.items():
            moves = standardized_moves(closes, days)
            if len(moves) < 200:
                raise ValueError(f'Not enough history for {key} ranges ({len(moves)} samples)')
            dates = moves.index.unique().sort_values()
            cutoff = dates[int(len(dates) * (1 - self.test_fraction))]
            # Purge: calibration moves must end before the held-out period starts
            purge = dates[max(0, dates.searchsorted(cutoff) - days)]
            calibration = moves[moves.index < purge]['z'].to_numpy()
            held_out = moves[moves.index >= cutoff]['z'].to_numpy()
            held_quantiles = range_quantiles(calibration)
            self.evaluation[key] = {
                **coverage(held_out, held_quantiles), 'days': days,
                'test_start': str(cutoff.date()), 'test_end': str(dates[-1].date()),
            }
            self.quantiles[key] = range_quantiles(moves['z'].to_numpy())
            logger.info(f"{key} ranges ({days}d): held-out coverage 50% {self.evaluation[key]['coverage_50']:.2f}, "
                        f"90% {self.evaluation[key]['coverage_90']:.2f} on {self.evaluation[key]['samples']} samples")
        return self.evaluation

    def ranges(self, price: float, sigma: float, key: str) -> Dict[str, float]:
        """Price levels of the range for one asset and horizon."""
        days = self.horizons[key]
        scale = sigma * np.sqrt(days)
        levels = {name: float(price * np.exp(q * scale)) for name, q in self.quantiles[key].items()}
        return {**levels, 'q50': float(price), 'days': days}

    def predict(self, closes: Dict[str, pd.Series]) -> List[Dict]:
        """Ranges from each asset's latest close, for every horizon."""
        if not self.quantiles:
            raise ValueError('Fit the forecaster first')
        result = []
        for symbol, close in closes.items():
            close = close.dropna()
            if len(close) < MIN_HISTORY:
                continue
            sigma = float(daily_volatility(close).iloc[-1])
            if not np.isfinite(sigma) or sigma <= 0:
                continue
            base_price = float(close.iloc[-1])
            for key in self.horizons:
                result.append({'symbol': symbol, 'horizon': key, 'base_date': str(close.index[-1].date()),
                               'base_price': base_price, 'sigma': sigma, **self.ranges(base_price, sigma, key)})
        return result

    def backtest(self, closes: Dict[str, pd.Series], periods: int = 60) -> List[Dict]:
        """
        Forecasts as they would have been made on each of the last ``periods``
        dates (quantiles from earlier dates only), scored against what happened.
        Used to give a new demo dashboard a simulated reliability history.
        """
        records = []
        for key, days in self.horizons.items():
            moves = standardized_moves(closes, days)
            dates = moves.index.unique().sort_values()
            for date in dates[-periods:]:
                past = moves[moves.index < dates[max(0, dates.searchsorted(date) - days)]]['z'].to_numpy()
                if len(past) < 200:
                    continue
                quantiles = range_quantiles(past)
                for symbol, close in closes.items():
                    close = close.dropna()
                    if date not in close.index:
                        continue
                    position = close.index.get_loc(date)
                    if position + days >= len(close) or position < MIN_HISTORY:
                        continue
                    sigma = float(daily_volatility(close.iloc[:position + 1]).iloc[-1])
                    base = float(close.iloc[position])
                    scale = sigma * np.sqrt(days)
                    levels = {name: float(base * np.exp(q * scale)) for name, q in quantiles.items()}
                    realized = float(close.iloc[position + days])
                    records.append({'symbol': symbol, 'horizon': key, 'days': days, 'base_date': str(date.date()),
                                    'base_price': base, 'sigma': sigma, 'q50': base, **levels,
                                    'target_date': str(close.index[position + days].date()),
                                    'realized_price': realized, **inside(realized, levels)})
        return records


def inside(realized: float, levels: Dict[str, float]) -> Dict[str, int]:
    return {'inside_50': int(levels['q25'] <= realized <= levels['q75']),
            'inside_90': int(levels['q05'] <= realized <= levels['q95'])}


def reliability(rows: List[Dict], recent: Optional[int] = None) -> Dict[str, float]:
    """Share of scored forecasts whose outcome landed inside each range."""
    scored = [r for r in rows if r.get('inside_90') is not None]
    if recent:
        scored = sorted(scored, key=lambda r: r['base_date'])[-recent:]
    if not scored:
        return {'scored': 0, 'coverage_50': None, 'coverage_90': None}
    return {'scored': len(scored),
            'coverage_50': float(np.mean([r['inside_50'] for r in scored])),
            'coverage_90': float(np.mean([r['inside_90'] for r in scored]))}
