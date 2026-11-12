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
from src.backtest.backtester import regress_on_universe
from src.data.synthetic import SyntheticDataCollector
from src.prediction import create_pipeline
from conftest import CRYPTO_SYMBOLS, SYMBOLS, make_ranker


@pytest.mark.slow
def test_result_structure(fast_config_path):
    ranker = make_ranker(fast_config_path)
    result = Backtester(ranker, top_n=3, test_days=40, use_ml=False).run_symbols(SYMBOLS[:10])

    assert ranker.horizon == 5
    assert len(result.daily) == 8  # 40 days / 5-day holding periods
    gaps = pd.Series(result.daily.index).diff().dropna()
    assert (gaps >= pd.Timedelta(days=5)).all()
    assert {'composite', 'composite_net', 'universe', 'turnover', 'quintile_spread', 'composite_ic'} \
        <= set(result.daily.columns)
    assert len(result.picks) == 8 * 3
    assert result.picks.groupby('date')['weight'].sum().round(6).eq(1).all()
    assert {'Composite after costs', 'Equal-weight universe'} <= set(result.metrics.index)
    assert 'Composite (no costs)' in result.ic
    assert result.daily['turnover'].between(0, 1).all()
    assert (result.daily['composite_net'] <= result.daily['composite'] + 1e-12).all()
    assert 'Backtest' in result.summary_text()
    benchmark = result.metrics.loc['Equal-weight universe']
    assert (benchmark['beta'], benchmark['alpha_per_year']) == (1.0, 0.0)
    assert result.metrics[['beta', 'alpha_per_year', 'alpha_t_stat']].columns.size == 3


@pytest.mark.slow
def test_portfolio_returns_match_the_data(fast_config_path):
    ranker = make_ranker(fast_config_path)
    prepared = ranker.fetch_and_prepare_data(SYMBOLS[:10])
    result = Backtester(ranker, top_n=3, test_days=30, use_ml=False).run(prepared)

    for _, pick in result.picks.iterrows():
        expected = prepared[pick['symbol']].loc[pick['date'], 'Future_Return']
        assert pick['return'] == pytest.approx(expected)
    weighted = result.picks.assign(c=lambda p: p['weight'] * p['return']).groupby('date')['c'].sum()
    assert np.allclose(weighted.values, result.daily['composite'].values)


@pytest.mark.slow
@pytest.mark.parametrize('use_ml', [False, True])
def test_no_lookahead_future_prices_do_not_change_past_picks(fast_config_path, use_ml):
    collector = SyntheticDataCollector(days=400, seed=11)
    raw = collector.fetch_many_prices(SYMBOLS[:10])
    ranker = create_pipeline('stocks', fast_config_path, data_collector=collector)
    original = ranker.prepare_universe(raw)

    # Scramble every price from the cutoff onwards
    dates = next(iter(raw.values())).index
    cutoff = dates[-20]
    rng = np.random.default_rng(99)
    scrambled = {}
    for symbol, frame in raw.items():
        frame = frame.copy()
        after = frame.index >= cutoff
        shock = np.exp(np.cumsum(rng.normal(0, 0.05, after.sum())))
        for column in ('Open', 'High', 'Low', 'Close'):
            frame.loc[after, column] *= shock
        frame.loc[after, 'Volume'] *= rng.uniform(0.2, 5, after.sum())
        scrambled[symbol] = frame
    altered = ranker.prepare_universe(scrambled)

    kwargs = dict(top_n=3, test_days=100, retrain_every=10, min_train_days=100, use_ml=use_ml)
    picks_a = Backtester(ranker, **kwargs).run(original).picks
    picks_b = Backtester(ranker, **kwargs).run(altered).picks

    # A decision at the close of t only sees data up to t; its realised return
    # (which runs to t + horizon) may legitimately cross the cutoff.
    decided_before = lambda p: p[p['date'] < cutoff][['date', 'rank', 'symbol', 'score', 'weight']].reset_index(drop=True)
    assert len(decided_before(picks_a)) > 0
    pd.testing.assert_frame_equal(decided_before(picks_a), decided_before(picks_b))


@pytest.mark.slow
def test_no_edge_without_signal_and_ml_finds_planted_signal(daily_config_path):
    kwargs = dict(top_n=4, test_days=100, retrain_every=25, min_train_days=150)
    symbols = SYMBOLS + [f"TSU{chr(65 + i)}" for i in range(8)]

    noise = Backtester(make_ranker(daily_config_path, reversal=0.0, seed=21), **kwargs).run_symbols(symbols)
    t_noise = noise.metrics['excess_t_stat'].dropna()
    assert (t_noise.abs() < 3).all(), f"significant edge on pure noise suggests lookahead:\n{t_noise}"
    assert abs(noise.ic['ML only']['ic_t_stat']) < 3

    signal = Backtester(make_ranker(daily_config_path, reversal=0.3, seed=21), **kwargs).run_symbols(symbols)
    assert signal.ic['ML only']['ic_t_stat'] > 3
    assert signal.metrics.loc['ML only', 'excess_t_stat'] > 2


@pytest.mark.slow
def test_crypto_backtest_uses_calendar_days(fast_config_path):
    ranker = make_ranker(fast_config_path, universe='crypto')
    result = Backtester(ranker, top_n=3, test_days=30, use_ml=False).run_symbols(CRYPTO_SYMBOLS)
    assert result.settings['universe'] == 'crypto'
    gaps = pd.Series(result.daily.index).diff().dropna()
    assert (gaps == pd.Timedelta(days=5)).all()  # 7-day calendar: 5 days = 5 calendar days


def test_from_config_and_validation(fast_config_path):
    ranker = make_ranker(fast_config_path)
    tester = Backtester.from_config(ranker, top_n=2, test_days=None)
    assert tester.top_n == 2
    assert tester.test_days == ranker.config['backtest']['test_days']

    with pytest.raises(ValueError):
        Backtester(ranker, top_n=10, use_ml=False).run_symbols(SYMBOLS[:5])


def periods(n=200, seed=7):
    """A universe return series and noise, for building strategies with a known beta and alpha."""
    rng = np.random.default_rng(seed)
    index = pd.date_range('2024-01-01', periods=n, freq='5D')
    return pd.Series(rng.normal(0.003, 0.02, n), index=index), pd.Series(rng.normal(0, 0.004, n), index=index)


def test_beta_and_alpha_are_recovered_from_a_strategy_with_both():
    universe, noise = periods()
    fit = regress_on_universe(0.002 + 1.5 * universe + noise, universe)
    assert fit['beta'] == pytest.approx(1.5, abs=0.1)
    assert fit['alpha'] == pytest.approx(0.002, abs=0.001)
    assert fit['alpha_t_stat'] > 3


def test_market_risk_alone_is_not_mistaken_for_skill():
    """A strategy that only leans on the market (beta 1.3, no alpha) beats it in a rising market, but alpha is about 0."""
    universe, noise = periods(seed=11)
    strategy = 1.3 * universe + noise
    assert (strategy - universe).mean() > 0                 # it "beats the universe" on average...
    fit = regress_on_universe(strategy, universe)
    assert fit['beta'] == pytest.approx(1.3, abs=0.1)
    assert abs(fit['alpha_t_stat']) < 2                     # ...yet there is no evidence of skill


def test_regression_needs_enough_periods_and_a_moving_universe():
    universe, noise = periods(n=3)
    assert np.isnan(regress_on_universe(universe + noise, universe)['beta'])
    flat = pd.Series(0.01, index=universe.index)
    assert np.isnan(regress_on_universe(noise, flat)['alpha'])


def test_metrics_report_beta_and_alpha_per_year_for_each_strategy():
    universe, noise = periods()
    daily = pd.DataFrame({'universe': universe, 'composite_net': 0.002 + 1.5 * universe + noise})
    backtester = object.__new__(Backtester)
    backtester.periods_per_year = 52
    metrics = backtester._metrics(daily)
    strategy, benchmark = metrics.loc['Composite after costs'], metrics.loc['Equal-weight universe']
    assert strategy['beta'] == pytest.approx(1.5, abs=0.1)
    assert strategy['alpha_per_year'] == pytest.approx(0.002 * 52, abs=0.052)
    assert (benchmark['beta'], benchmark['alpha_per_year']) == (1.0, 0.0) and np.isnan(benchmark['alpha_t_stat'])
