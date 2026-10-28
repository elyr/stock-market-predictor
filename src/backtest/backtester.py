"""
Walk-forward backtest of the daily top-N picks.

For each trading day t in the test window the backtester does what the live
system would have done at the close of day t, using only information available
then:

1. Score every stock from its history up to and including t (technical,
   momentum, volume, and the ML model).
2. Pick the top N by composite score (and, for attribution, by each component
   on its own).
3. Hold the picks from the close of t to the close of t+1 and record their
   average return, against the equal-weight average of the whole universe.

The ML models are retrained every ``retrain_every`` days on rows dated strictly
before t. A row dated d has a label that depends on the close of d+1, which is
known by the close of t whenever d < t, so no future information is used.

Sentiment is left out: historical news and sector snapshots are not available
for past dates, and the composite renormalises over the remaining weights.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.models.ml_models import StockPredictor
from src.prediction.stock_ranker import PRICE_BASED_COMPONENTS, StockRanker, composite_score

logger = logging.getLogger(__name__)

TRADING_DAYS = 252
SCORE_HISTORY = 60  # rows of history passed to the scoring functions (they look back at most ~20)

STRATEGY_LABELS = {
    'composite': 'Composite score',
    'technical_score': 'Technical only',
    'momentum_score': 'Momentum only',
    'volume_score': 'Volume only',
    'ml_prediction': 'ML only',
}


@dataclass
class BacktestResult:
    """Outcome of a backtest run."""

    daily: pd.DataFrame
    """One row per test day: each strategy's next-day return, the universe's, and composite turnover."""
    metrics: pd.DataFrame
    """One row per strategy with return, risk and hit-rate statistics."""
    picks: pd.DataFrame
    """Every composite pick: date, rank, symbol, score and realised next-day return."""
    settings: Dict = field(default_factory=dict)

    def summary_text(self) -> str:
        """Plain-text summary for logs and the terminal."""
        lines = [
            f"Backtest {self.settings.get('start')} to {self.settings.get('end')} "
            f"({self.settings.get('days')} trading days, {self.settings.get('universe_size')} stocks, "
            f"top {self.settings.get('top_n')}, cost {self.settings.get('cost_bps')} bps one-way)",
            "",
            self.metrics.to_string(float_format=lambda v: f"{v:,.4f}"),
        ]
        return "\n".join(lines)


class Backtester:
    """
    Simulates the ranker's daily picks over past data.

    Args:
        ranker: A configured :class:`StockRanker` (its scoring rules, weights,
            filters and ML config are reused)
        top_n: Number of picks per day
        test_days: How many of the most recent days to simulate
        retrain_every: Days between ML retrains
        min_train_days: Days of history required before the first ML model
        cost_bps: One-way transaction cost in basis points, charged on turnover
        use_ml: Include the ML component (slower)
    """

    def __init__(self, ranker: StockRanker, top_n: int = 10, test_days: int = 120,
                 retrain_every: int = 20, min_train_days: int = 120, cost_bps: float = 5.0,
                 use_ml: bool = True):
        self.ranker = ranker
        self.top_n = top_n
        self.test_days = test_days
        self.retrain_every = max(1, retrain_every)
        self.min_train_days = min_train_days
        self.cost_bps = cost_bps
        self.use_ml = use_ml and ranker.weights.get('ml_prediction', 0) > 0

        self.weights = {k: v for k, v in ranker.weights.items() if k != 'sentiment_score'}
        if not self.use_ml:
            self.weights.pop('ml_prediction', None)

    @classmethod
    def from_config(cls, ranker: StockRanker, **overrides) -> 'Backtester':
        """Build a backtester from the ``backtest`` section of the ranker's config."""
        cfg = ranker.config.get('backtest', {})
        params = {
            'top_n': ranker.ranking_config.get('top_picks', 10),
            'test_days': cfg.get('test_days', 120),
            'retrain_every': cfg.get('retrain_every', 20),
            'min_train_days': cfg.get('min_train_days', 120),
            'cost_bps': cfg.get('cost_bps', 5.0),
        }
        params.update({k: v for k, v in overrides.items() if v is not None})
        return cls(ranker, **params)

    # ------------------------------------------------------------------ run

    def run_symbols(self, symbols: List[str], period: Optional[str] = None) -> BacktestResult:
        """Fetch, prepare and backtest the given symbols."""
        period = period or self.ranker.config.get('backtest', {}).get('period', '2y')
        prepared = self.ranker.fetch_and_prepare_data(symbols, period=period)
        return self.run(prepared)

    def run(self, prepared_data: Dict[str, pd.DataFrame]) -> BacktestResult:
        """
        Backtest on already-prepared data (output of ``StockRanker.fetch_and_prepare_data``).
        """
        prepared_data = {s: d for s, d in prepared_data.items() if d is not None and len(d) > 30}
        if len(prepared_data) < self.top_n + 1:
            raise ValueError(f"Need more than top_n={self.top_n} stocks to backtest, got {len(prepared_data)}")

        calendar = pd.DatetimeIndex(sorted(set().union(*(d.index for d in prepared_data.values()))))
        # The last date has no next-day return yet
        test_dates = calendar[:-1][-self.test_days:]
        if len(test_dates) == 0:
            raise ValueError("Not enough history for the requested test window")

        pooled = self._pool(prepared_data) if self.use_ml else None
        positions = {s: pd.Series(np.arange(len(d)), index=d.index) for s, d in prepared_data.items()}

        predictor: Optional[StockPredictor] = None
        last_train = None
        daily_rows, pick_rows = [], []
        previous_picks: List[str] = []

        logger.info(f"Backtesting {len(test_dates)} days over {len(prepared_data)} stocks...")
        for step, date in enumerate(test_dates):
            if self.use_ml and (last_train is None or step - last_train >= self.retrain_every):
                predictor = self._train(pooled, date) or predictor
                last_train = step

            frame = self._score_day(prepared_data, positions, date, predictor)
            if len(frame) <= self.top_n:
                continue

            row = {'date': date, 'universe': frame['future_return'].mean(), 'n_stocks': len(frame)}
            for strategy in ['composite', *PRICE_BASED_COMPONENTS, 'ml_prediction']:
                if strategy not in frame.columns or frame[strategy].isna().all():
                    continue
                top = frame.nlargest(self.top_n, strategy)
                row[strategy] = top['future_return'].mean()
                if strategy == 'composite':
                    picks = list(top.index)
                    changed = len(set(picks) - set(previous_picks)) / self.top_n
                    # Selling the dropped names and buying the new ones: two one-way costs on the changed share
                    row['turnover'] = changed
                    row['composite_net'] = row['composite'] - changed * (2 if previous_picks else 1) * self.cost_bps / 1e4
                    previous_picks = picks
                    for rank, (symbol, pick) in enumerate(top.iterrows(), 1):
                        pick_rows.append({'date': date, 'rank': rank, 'symbol': symbol,
                                          'score': pick['composite'], 'next_day_return': pick['future_return']})
            daily_rows.append(row)

        daily = pd.DataFrame(daily_rows).set_index('date')
        picks = pd.DataFrame(pick_rows)
        metrics = self._metrics(daily)
        settings = {
            'start': daily.index[0].date() if len(daily) else None,
            'end': daily.index[-1].date() if len(daily) else None,
            'days': len(daily),
            'universe_size': len(prepared_data),
            'top_n': self.top_n,
            'cost_bps': self.cost_bps,
            'retrain_every': self.retrain_every,
            'use_ml': self.use_ml,
            'weights': self.weights,
        }
        return BacktestResult(daily=daily, metrics=metrics, picks=picks, settings=settings)

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _pool(prepared_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        frames = []
        for symbol, data in prepared_data.items():
            frame = data.copy()
            frame['Symbol'] = symbol
            frames.append(frame)
        return pd.concat(frames).sort_index(kind='stable')

    def _train(self, pooled: pd.DataFrame, date: pd.Timestamp) -> Optional[StockPredictor]:
        """Train a fresh model on rows dated strictly before ``date``."""
        history = pooled[pooled.index < date].dropna(subset=['Target_Up'])
        if history.index.nunique() < self.min_train_days:
            return None
        predictor = StockPredictor(self.ranker.config.get('ml_config', {}))
        try:
            predictor.train_all_models(history, test_size=0, cross_validate=False)
        except ValueError as e:
            logger.warning(f"ML retrain on {date.date()} skipped: {e}")
            return None
        logger.info(f"Retrained ML on {len(history)} rows before {date.date()}")
        return predictor if predictor.models else None

    def _score_day(self, prepared_data: Dict[str, pd.DataFrame], positions: Dict[str, pd.Series],
                   date: pd.Timestamp, predictor: Optional[StockPredictor]) -> pd.DataFrame:
        """Score every eligible stock as of the close of ``date``."""
        rows, latest_rows = {}, []
        for symbol, data in prepared_data.items():
            if date not in positions[symbol].index:
                continue
            pos = int(positions[symbol][date])
            future = data['Future_Return'].iloc[pos]
            if pd.isna(future) or pos < 30:
                continue
            window = data.iloc[max(0, pos - SCORE_HISTORY + 1):pos + 1]
            if not self.ranker.apply_filters(symbol, window):
                continue
            patterns = self.ranker.technical_analyzer.detect_chart_patterns(window)
            scores = self.ranker.score_components(window, patterns)
            scores['future_return'] = future
            rows[symbol] = scores
            latest_rows.append(window.iloc[[-1]])

        frame = pd.DataFrame.from_dict(rows, orient='index')
        if frame.empty:
            return frame

        if predictor is not None:
            latest = pd.concat(latest_rows)
            frame['ml_prediction'] = predictor.predict(latest)['probabilities'] * 100
        else:
            frame['ml_prediction'] = np.nan

        components = [c for c in self.weights if c in frame.columns]
        frame['composite'] = [
            composite_score({c: (None if pd.isna(r[c]) else r[c]) for c in components}, self.weights)
            for _, r in frame.iterrows()
        ]
        return frame

    def _metrics(self, daily: pd.DataFrame) -> pd.DataFrame:
        """Return, risk and hit-rate statistics for each strategy column."""
        columns = [c for c in ['composite_net', 'composite', *PRICE_BASED_COMPONENTS, 'ml_prediction', 'universe']
                   if c in daily.columns and daily[c].notna().any()]
        labels = {**STRATEGY_LABELS, 'composite_net': 'Composite after costs', 'universe': 'Equal-weight universe'}

        rows = {}
        for col in columns:
            r = daily[col].dropna()
            if r.empty:
                continue
            equity = (1 + r).cumprod()
            excess = (r - daily.loc[r.index, 'universe'])
            vol = r.std() * np.sqrt(TRADING_DAYS)
            rows[labels.get(col, col)] = {
                'total_return': equity.iloc[-1] - 1,
                'annualized_return': equity.iloc[-1] ** (TRADING_DAYS / len(r)) - 1,
                'annualized_volatility': vol,
                'sharpe': (r.mean() * TRADING_DAYS) / vol if vol > 0 else np.nan,
                'max_drawdown': (equity / equity.cummax() - 1).min(),
                'avg_daily_excess_bps': excess.mean() * 1e4,
                'excess_t_stat': (excess.mean() / excess.std() * np.sqrt(len(excess))
                                  if col != 'universe' and excess.std() > 0 else np.nan),
                'days_beating_universe': (excess > 0).mean() if col != 'universe' else np.nan,
            }
        return pd.DataFrame.from_dict(rows, orient='index')
