"""
Tests for the walk-forward backtest.

The most important property is that the backtest never uses information from
after the decision date. Two independent checks cover that:

* changing prices *after* a date must not change any pick made before it, and
* on data with no predictable signal, no strategy shows significant edge.
"""

import numpy as np
import pandas as pd
import pytest

from src.backtest import Backtester
from src.data.synthetic import SyntheticDataCollector
from src.prediction.stock_ranker import StockRanker
from conftest import SYMBOLS, make_ranker


def test_result_structure(fast_config_path):
    ranker = make_ranker(fast_config_path)
    result = Backtester(ranker, top_n=3, test_days=30, use_ml=False).run_symbols(SYMBOLS[:10])

    assert len(result.daily) == 30
    assert {'composite', 'composite_net', 'universe', 'turnover'} <= set(result.daily.columns)
    assert len(result.picks) == 30 * 3
    assert result.picks.groupby('date')['rank'].apply(list).map(lambda r: r == [1, 2, 3]).all()
    assert 'Composite after costs' in result.metrics.index
    assert 'Equal-weight universe' in result.metrics.index
    assert result.daily['turnover'].between(0, 1).all()
    assert (result.daily['composite_net'] <= result.daily['composite'] + 1e-12).all()
    assert 'Backtest' in result.summary_text()


def test_pick_returns_match_the_data(fast_config_path):
    ranker = make_ranker(fast_config_path)
    prepared = ranker.fetch_and_prepare_data(SYMBOLS[:10])
    result = Backtester(ranker, top_n=3, test_days=10, use_ml=False).run(prepared)

    for _, pick in result.picks.iterrows():
        expected = prepared[pick['symbol']].loc[pick['date'], 'Future_Return']
        assert pick['next_day_return'] == pytest.approx(expected)
    daily_mean = result.picks.groupby('date')['next_day_return'].mean()
    assert np.allclose(daily_mean.values, result.daily['composite'].values)


@pytest.mark.parametrize('use_ml', [False, True])
def test_no_lookahead_future_prices_do_not_change_past_picks(fast_config_path, use_ml):
    collector = SyntheticDataCollector(days=400, seed=11)
    raw = collector.fetch_multiple_stocks(SYMBOLS[:10])
    ranker = StockRanker(fast_config_path, data_collector=collector)
    original = {s: ranker.prepare_symbol_data(d) for s, d in raw.items()}

    # Scramble every price from the cutoff onwards
    dates = next(iter(raw.values())).index
    cutoff = dates[-15]
    rng = np.random.default_rng(99)
    altered = {}
    for symbol, frame in raw.items():
        frame = frame.copy()
        after = frame.index >= cutoff
        shock = np.exp(np.cumsum(rng.normal(0, 0.05, after.sum())))
        for column in ('Open', 'High', 'Low', 'Close'):
            frame.loc[after, column] *= shock
        frame.loc[after, 'Volume'] *= rng.uniform(0.2, 5, after.sum())
        altered[symbol] = ranker.prepare_symbol_data(frame)

    kwargs = dict(top_n=3, test_days=40, retrain_every=10, min_train_days=100, use_ml=use_ml)
    picks_a = Backtester(ranker, **kwargs).run(original).picks
    picks_b = Backtester(ranker, **kwargs).run(altered).picks

    # Decisions made at the close of a day before the cutoff only see data up to that day.
    # (The realised return of the last pre-cutoff day legitimately differs.)
    before = lambda p: p[p['date'] < cutoff][['date', 'rank', 'symbol', 'score']].reset_index(drop=True)
    pd.testing.assert_frame_equal(before(picks_a), before(picks_b))
    assert not picks_a[picks_a['date'] >= cutoff].equals(picks_b[picks_b['date'] >= cutoff])


def test_no_edge_without_signal_and_ml_finds_planted_signal(fast_config_path):
    kwargs = dict(top_n=4, test_days=120, retrain_every=30, min_train_days=150)

    noise = Backtester(make_ranker(fast_config_path, reversal=0.0, seed=21), **kwargs).run_symbols(SYMBOLS)
    t_noise = noise.metrics['excess_t_stat'].dropna()
    assert (t_noise.abs() < 3).all(), f"significant edge on pure noise suggests lookahead:\n{t_noise}"

    signal = Backtester(make_ranker(fast_config_path, reversal=0.3, seed=21), **kwargs).run_symbols(SYMBOLS)
    assert signal.metrics.loc['ML only', 'excess_t_stat'] > 3


def test_from_config_and_validation(fast_config_path):
    ranker = make_ranker(fast_config_path)
    tester = Backtester.from_config(ranker, top_n=2, test_days=None)
    assert tester.top_n == 2
    assert tester.test_days == ranker.config['backtest']['test_days']
    assert 'sentiment_score' not in tester.weights

    with pytest.raises(ValueError):
        Backtester(ranker, top_n=10, use_ml=False).run_symbols(SYMBOLS[:5])
