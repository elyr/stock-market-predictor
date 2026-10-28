"""
Walk-forward backtest of the pipeline's picks.

Every ``horizon`` days (the rebalance date t), the backtester does what the
live system would have done at the close of t, using only information
available then:

1. Score every asset from its history up to and including t (technical,
   momentum, volume, and the ML model, as a cross-sectional percentile).
2. Build the portfolio exactly as the live system does: top N by composite
   score, sector cap, inverse-volatility or equal weights. For attribution it
   also picks the top N by each component on its own.
3. Hold until t + horizon and record the portfolio's return against the
   equal-weight average of the whole universe.

ML models are retrained every ``retrain_every`` days on rows whose labels were
fully known at t: a row dated d has a label that depends on the close of
d + horizon, so only rows with d + horizon <= t are used (purged training).

Ranking quality is also measured directly with the information coefficient
(rank correlation between score and subsequent return across assets) and the
spread between the top and bottom quintiles.

Sentiment is left out: historical news and sector snapshots are not available
for past dates, and the composite renormalises over the remaining weights.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.models.ml_models import StockPredictor
from src.prediction.portfolio import select_portfolio
from src.prediction.stock_ranker import PRICE_BASED_COMPONENTS, StockRanker, composite_score, percentile_scores

logger = logging.getLogger(__name__)

SCORE_HISTORY = 60  # rows passed to the scoring functions (they look back at most ~20)

STRATEGY_LABELS = {
    'composite_net': 'Composite after costs',
    'composite': 'Composite (no costs)',
    'technical_score': 'Technical only',
    'momentum_score': 'Momentum only',
    'volume_score': 'Volume only',
    'ml_prediction': 'ML only',
    'universe': 'Equal-weight universe',
}


@dataclass
class BacktestResult:
    """Outcome of a backtest run."""

    daily: pd.DataFrame
    """One row per rebalance date: each strategy's return over the holding period,
    the universe's, composite turnover, and the composite's IC and quintile spread."""
    metrics: pd.DataFrame
    """One row per strategy with return, risk and hit-rate statistics."""
    picks: pd.DataFrame
    """Every composite pick: date, rank, symbol, weight, score and realised return."""
    predictions: pd.DataFrame = field(default_factory=pd.DataFrame)
    """Every scored asset on every rebalance date: its scores, model probability,
    whether it was picked, and what actually happened next (the prediction log)."""
    ic: Dict[str, Dict[str, float]] = field(default_factory=dict)
    """Information-coefficient summary per score (composite and each component)."""
    settings: Dict = field(default_factory=dict)

    def summary_text(self) -> str:
        """Plain-text summary for logs and the terminal."""
        s = self.settings
        lines = [
            f"Backtest {s.get('universe')} {s.get('start')} to {s.get('end')} "
            f"({s.get('periods')} periods of {s.get('horizon')} days, {s.get('universe_size')} assets, "
            f"top {s.get('top_n')}, cost {s.get('cost_bps')} bps one-way)",
            "",
            self.metrics.to_string(float_format=lambda v: f"{v:,.4f}"),
            "",
            pd.DataFrame(self.ic).T.to_string(float_format=lambda v: f"{v:,.4f}"),
        ]
        return "\n".join(lines)


def summarize_ic(values: pd.Series, periods_per_year: float) -> Dict[str, float]:
    """Mean, t-statistic, share positive and annualized information ratio of a series of ICs."""
    v = values.dropna()
    if len(v) < 2 or v.std() == 0:
        return {'ic_mean': float(v.mean()) if len(v) else float('nan'), 'ic_t_stat': float('nan'),
                'ic_positive_share': float((v > 0).mean()) if len(v) else float('nan'),
                'ic_ir': float('nan'), 'periods': int(len(v))}
    return {
        'ic_mean': float(v.mean()),
        'ic_t_stat': float(v.mean() / v.std() * np.sqrt(len(v))),
        'ic_positive_share': float((v > 0).mean()),
        'ic_ir': float(v.mean() / v.std() * np.sqrt(periods_per_year)),
        'periods': int(len(v)),
    }


class Backtester:
    """
    Simulates a pipeline's picks over past data.

    Args:
        ranker: A configured pipeline (its scoring rules, weights, filters,
            portfolio rules, horizon and ML config are reused)
        top_n: Number of positions
        test_days: How many of the most recent days to simulate
        retrain_every: Days between ML retrains
        min_train_days: Days of labelled history required before the first ML model
        cost_bps: One-way transaction cost in basis points, charged on turnover
        use_ml: Include the ML component (slower)
    """

    def __init__(self, ranker: StockRanker, top_n: int = 10, test_days: int = 120,
                 retrain_every: int = 20, min_train_days: int = 120, cost_bps: float = 5.0,
                 use_ml: bool = True, end_date: Optional[str] = None, start_date: Optional[str] = None):
        self.ranker = ranker
        self.top_n = top_n
        self.test_days = test_days
        self.retrain_every = max(1, retrain_every)
        self.min_train_days = min_train_days
        self.cost_bps = cost_bps
        self.horizon = ranker.horizon
        self.periods_per_year = ranker.periods_per_year / self.horizon
        self.use_ml = use_ml and ranker.weights.get('ml_prediction', 0) > 0
        # Optional decision window: experiments use it to keep a locked recent period out of sight
        self.end_date = pd.Timestamp(end_date) if end_date else None
        self.start_date = pd.Timestamp(start_date) if start_date else None

        self.weights = {k: v for k, v in ranker.weights.items() if k != 'sentiment_score'}
        if not self.use_ml:
            self.weights.pop('ml_prediction', None)

    @classmethod
    def from_config(cls, ranker: StockRanker, **overrides) -> 'Backtester':
        """Build a backtester from the ``backtest`` section of the pipeline's config."""
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

    def run_symbols(self, symbols: Optional[List[str]] = None, period: Optional[str] = None) -> BacktestResult:
        """Fetch, prepare and backtest the given symbols (default: the universe's list)."""
        period = period or self.ranker.config.get('backtest', {}).get('period', '2y')
        prepared = self.ranker.fetch_and_prepare_data(symbols or self.ranker.symbols, period=period)
        return self.run(prepared)

    def run(self, prepared_data: Dict[str, pd.DataFrame]) -> BacktestResult:
        """Backtest on already-prepared data (output of ``fetch_and_prepare_data``)."""
        prepared_data = {s: d for s, d in prepared_data.items() if d is not None and len(d) > 30}
        if len(prepared_data) < self.top_n + 1:
            raise ValueError(f"Need more than top_n={self.top_n} assets to backtest, got {len(prepared_data)}")

        calendar = pd.DatetimeIndex(sorted(set().union(*(d.index for d in prepared_data.values()))))
        # Decision dates need a known return `horizon` days later; rebalance every `horizon` days
        decidable = calendar[:-self.horizon] if len(calendar) > self.horizon else calendar[:0]
        if self.end_date is not None:
            decidable = decidable[decidable <= self.end_date]
        if self.start_date is not None:
            decidable = decidable[decidable >= self.start_date]
        window = decidable[-self.test_days:]
        rebalance_dates = window[::-1][::self.horizon][::-1]
        if len(rebalance_dates) == 0:
            raise ValueError("Not enough history for the requested test window")

        pooled = self.ranker.pool(prepared_data) if self.use_ml else None
        positions = {s: pd.Series(np.arange(len(d)), index=d.index) for s, d in prepared_data.items()}
        calendar_pos = pd.Series(np.arange(len(calendar)), index=calendar)

        predictor: Optional[StockPredictor] = None
        last_train_pos = None
        rows, pick_rows, ic_rows, prediction_frames = [], [], [], []
        previous_weights: Dict[str, float] = {}

        logger.info(f"Backtesting {len(rebalance_dates)} rebalances over {len(prepared_data)} assets...")
        for date in rebalance_dates:
            pos = int(calendar_pos[date])
            if self.use_ml and (last_train_pos is None or pos - last_train_pos >= self.retrain_every):
                cutoff = calendar[pos - self.horizon] if pos - self.horizon >= 0 else None
                predictor = (self._train(pooled, cutoff) if cutoff is not None else None) or predictor
                last_train_pos = pos

            frame = self._score_day(prepared_data, positions, date, predictor)
            if len(frame) <= self.top_n:
                continue

            row = {'date': date, 'universe': frame['future_return'].mean(), 'n_assets': len(frame)}
            ic_row = {'date': date}
            for strategy in ['composite', *PRICE_BASED_COMPONENTS, 'ml_prediction']:
                if strategy not in frame.columns or frame[strategy].isna().all():
                    continue
                ic_row[strategy] = spearmanr(frame[strategy], frame['future_return'])[0]
                if strategy == 'composite':
                    portfolio = select_portfolio(
                        frame, self.top_n, score_col='composite', sector_col='sector', vol_col='volatility',
                        max_per_sector=self.ranker.portfolio_config.get('max_per_sector', 0),
                        weighting=self.ranker.portfolio_config.get('weighting', 'equal'))
                    weights = portfolio['Weight'].to_dict()
                    gross = float((portfolio['Weight'] * portfolio['future_return']).sum())
                    traded = sum(abs(weights.get(s, 0) - previous_weights.get(s, 0))
                                 for s in set(weights) | set(previous_weights))
                    row.update({'composite': gross, 'turnover': traded / 2,
                                'composite_net': gross - traded * self.cost_bps / 1e4})
                    quintile = max(1, len(frame) // 5)
                    ordered = frame.sort_values('composite')
                    row['quintile_spread'] = (ordered['future_return'].tail(quintile).mean()
                                              - ordered['future_return'].head(quintile).mean())
                    previous_weights = weights
                    log = frame.drop(columns=['sector'], errors='ignore').copy()
                    log['sector'] = frame.get('sector')
                    log['weight'] = pd.Series(weights).reindex(log.index)
                    log['picked'] = log['weight'].notna()
                    log['rank'] = log['composite'].rank(ascending=False, method='first').astype(int)
                    log['universe_return'] = frame['future_return'].mean()
                    log['universe_volatility'] = frame['volatility'].mean()
                    prediction_frames.append(log.assign(date=date).rename_axis('symbol').reset_index())
                    for rank, (symbol, pick) in enumerate(portfolio.iterrows(), 1):
                        pick_rows.append({'date': date, 'rank': rank, 'symbol': symbol,
                                          'weight': pick['Weight'], 'score': pick['composite'],
                                          'return': pick['future_return']})
                else:
                    row[strategy] = frame.nlargest(self.top_n, strategy)['future_return'].mean()
            rows.append(row)
            ic_rows.append(ic_row)

        daily = pd.DataFrame(rows).set_index('date')
        ic_frame = pd.DataFrame(ic_rows).set_index('date')
        daily['composite_ic'] = ic_frame.get('composite')
        picks = pd.DataFrame(pick_rows)
        predictions = pd.concat(prediction_frames, ignore_index=True) if prediction_frames else pd.DataFrame()
        if not predictions.empty:
            predictions['excess_return'] = predictions['future_return'] - predictions['universe_return']
        metrics = self._metrics(daily)
        ic = {STRATEGY_LABELS.get(c, c): summarize_ic(ic_frame[c], self.periods_per_year) for c in ic_frame.columns}
        settings = {
            'universe': self.ranker.universe,
            'start': str(daily.index[0].date()) if len(daily) else None,
            'end': str(daily.index[-1].date()) if len(daily) else None,
            'periods': len(daily),
            'horizon': self.horizon,
            'universe_size': len(prepared_data),
            'top_n': self.top_n,
            'cost_bps': self.cost_bps,
            'retrain_every': self.retrain_every,
            'use_ml': self.use_ml,
            'weights': self.weights,
            'weighting': self.ranker.portfolio_config.get('weighting', 'equal'),
            'max_per_sector': self.ranker.portfolio_config.get('max_per_sector', 0),
            'end_date': str(self.end_date.date()) if self.end_date is not None else None,
        }
        return BacktestResult(daily=daily, metrics=metrics, picks=picks, ic=ic, settings=settings,
                              predictions=predictions)

    # -------------------------------------------------------------- helpers

    def _train(self, pooled: pd.DataFrame, cutoff: pd.Timestamp) -> Optional[StockPredictor]:
        """Train a fresh model on rows dated on or before ``cutoff`` (labels known by now)."""
        predictor = StockPredictor(self.ranker.config.get('ml_config', {}))
        history = pooled[pooled.index <= cutoff].dropna(subset=[predictor.target_column])
        if history.index.nunique() < self.min_train_days:
            return None
        try:
            predictor.train_all_models(history, test_size=0, cross_validate=False)
        except ValueError as e:
            logger.warning(f"ML retrain at {cutoff.date()} skipped: {e}")
            return None
        logger.info(f"Retrained ML on {len(history)} rows up to {cutoff.date()}")
        return predictor if predictor.models else None

    def _score_day(self, prepared_data: Dict[str, pd.DataFrame], positions: Dict[str, pd.Series],
                   date: pd.Timestamp, predictor: Optional[StockPredictor]) -> pd.DataFrame:
        """Score every eligible asset as of the close of ``date``."""
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
            last = window.iloc[-1]
            scores['future_return'] = future
            scores['volatility'] = last.get('Volatility_20d', np.nan)
            scores['sector'] = self.ranker.asset_metadata(symbol, None)['sector'] \
                if self.ranker.asset_class == 'crypto' else self._sector(symbol)
            rows[symbol] = scores
            latest_rows.append(window.iloc[[-1]])

        frame = pd.DataFrame.from_dict(rows, orient='index')
        if frame.empty:
            return frame

        if predictor is not None:
            latest = pd.concat(latest_rows)
            probabilities = pd.Series(predictor.predict(latest)['probabilities'], index=frame.index)
            frame['ml_probability'] = probabilities
            frame['ml_prediction'] = percentile_scores(probabilities)
        else:
            frame['ml_probability'] = np.nan
            frame['ml_prediction'] = np.nan

        components = [c for c in self.weights if c in frame.columns]
        frame['composite'] = [
            composite_score({c: (None if pd.isna(r[c]) else r[c]) for c in components}, self.weights)
            for _, r in frame.iterrows()
        ]
        return frame

    def _sector(self, symbol: str) -> Optional[str]:
        if not hasattr(self, '_sectors'):
            self._sectors: Dict[str, Optional[str]] = {}
        if symbol not in self._sectors:
            info = None
            if self.ranker.portfolio_config.get('max_per_sector', 0):
                try:
                    info = self.ranker.data_collector.fetch_company_info(symbol)
                except Exception:
                    info = None
            self._sectors[symbol] = (info or {}).get('sector')
        return self._sectors[symbol]

    def _metrics(self, daily: pd.DataFrame) -> pd.DataFrame:
        """Return, risk and hit-rate statistics for each strategy column."""
        columns = [c for c in ['composite_net', 'composite', *PRICE_BASED_COMPONENTS, 'ml_prediction', 'universe']
                   if c in daily.columns and daily[c].notna().any()]
        rows = {}
        for col in columns:
            r = daily[col].dropna()
            if r.empty:
                continue
            equity = (1 + r).cumprod()
            excess = r - daily.loc[r.index, 'universe']
            vol = r.std() * np.sqrt(self.periods_per_year)
            is_benchmark = col == 'universe'
            rows[STRATEGY_LABELS.get(col, col)] = {
                'total_return': equity.iloc[-1] - 1,
                'annualized_return': equity.iloc[-1] ** (self.periods_per_year / len(r)) - 1,
                'annualized_volatility': vol,
                'sharpe': (r.mean() * self.periods_per_year) / vol if vol > 0 else np.nan,
                'max_drawdown': (equity / equity.cummax() - 1).min(),
                'avg_excess_bps': excess.mean() * 1e4,
                'excess_t_stat': (excess.mean() / excess.std() * np.sqrt(len(excess))
                                  if not is_benchmark and excess.std() > 0 else np.nan),
                'periods_beating_universe': (excess > 0).mean() if not is_benchmark else np.nan,
            }
        return pd.DataFrame.from_dict(rows, orient='index')
