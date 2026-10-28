"""
Tests for the predicted-versus-actual comparator and experiment windows.
"""

import numpy as np
import pandas as pd
import pytest

from src.backtest import Backtester
from src.evaluation import build_report, split_periods, validate_settings
from src.evaluation.comparator import calibration_table, decile_table, normalize_log
from conftest import SYMBOLS, make_ranker


def synthetic_log(skill: float, dates: int = 40, assets: int = 30, seed: int = 0) -> pd.DataFrame:
    """Scores that predict excess returns with a chosen strength (0 = none)."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.bdate_range('2026-01-01', periods=dates):
        signal = rng.normal(size=assets)
        excess = skill * signal + rng.normal(size=assets)
        excess -= excess.mean()
        for i in range(assets):
            rows.append({'date': d, 'symbol': f'A{i}', 'composite': 50 + 10 * signal[i],
                         'ml_probability': 1 / (1 + np.exp(-skill * signal[i])), 'future_return': excess[i] / 100,
                         'universe_return': 0.0, 'universe_volatility': rng.uniform(0.01, 0.03),
                         'sector': 'Tech' if i % 2 else 'Energy', 'picked': False})
    log = pd.DataFrame(rows)
    log['rank'] = log.groupby('date')['composite'].rank(ascending=False).astype(int)
    log['picked'] = log['rank'] <= 5
    return log


def test_skilled_scores_make_a_staircase():
    report = build_report(synthetic_log(skill=0.5))
    buckets = report['deciles']['buckets']
    assert len(buckets) == 10
    assert report['deciles']['monotonicity'] > 0.9
    assert report['deciles']['spread'] > 0
    assert report['summary']['ic']['mean'] > 0.2 and report['summary']['ic']['t_stat'] > 5
    assert report['summary']['picked_hit_rate'] > 0.6


def test_unskilled_scores_show_no_edge():
    report = build_report(synthetic_log(skill=0.0, seed=3))
    assert abs(report['summary']['ic']['mean']) < 0.05
    assert abs(report['summary']['ic']['t_stat']) < 3


def test_calibration_reflects_probabilities():
    log = normalize_log(synthetic_log(skill=1.0))
    table = calibration_table(log)
    predicted = [b['predicted'] for b in table['bins']]
    observed = [b['observed'] for b in table['bins']]
    assert predicted == sorted(predicted) and observed == sorted(observed)
    assert table['brier'] < 0.25


def test_breakdowns_and_regimes():
    report = build_report(synthetic_log(skill=0.5))
    breakdowns = report['breakdowns']
    assert {b['group'] for b in breakdowns['sector']} == {'Tech', 'Energy'}
    assert {b['group'] for b in breakdowns['regime']} == {'Calm market', 'Normal market', 'Turbulent market'}
    assert sum(b['count'] for b in breakdowns['regime']) == 40 * 30


def test_rolling_ic_and_log():
    report = build_report(synthetic_log(skill=0.3), log_limit=10)
    assert len(report['ic_series']) == 40
    assert report['ic_series'][0]['rolling'] is None and report['ic_series'][-1]['rolling'] is not None
    assert len(report['log']) == 10 and report['log'][0]['rank'] == 1


def test_empty_log_is_handled():
    report = build_report(pd.DataFrame())
    assert report['summary']['predictions'] == 0 and report['deciles']['buckets'] == []


def test_decile_count_adapts_to_small_universes():
    small = synthetic_log(skill=0.5, assets=8)
    assert decile_table(normalize_log(small))['bucket_count'] == 4


def test_backtest_predictions_feed_the_comparator(daily_config_path):
    ranker = make_ranker(daily_config_path, reversal=0.3, seed=21)
    result = Backtester(ranker, top_n=4, test_days=60, retrain_every=30, min_train_days=150).run_symbols(SYMBOLS)
    report = build_report(result.predictions)
    components = {c['key']: c for c in report['components']}
    assert report['summary']['periods'] == 60
    assert components['ml_probability']['mean'] > 0.05           # the model finds the planted reversal
    assert components['momentum_score']['mean'] < 0               # momentum bets against it
    assert report['summary']['picked_count'] == 60 * 4


def test_experiment_windows_are_shared_and_never_overlap():
    calendar = pd.bdate_range('2025-01-01', periods=500)
    windows = [split_periods(calendar, h, lockbox_days=60, test_days=250) for h in (1, 5, 20)]
    assert len({(w['dev_start'], w['dev_end'], w['lockbox_start']) for w in windows}) == 1
    w = windows[-1]
    gap = calendar.get_loc(w['lockbox_start']) - calendar.get_loc(w['dev_end'])
    assert gap >= 20  # longest horizon: no development outcome inside the locked period
    with pytest.raises(ValueError):
        split_periods(calendar[:80], 5, lockbox_days=60, test_days=250)


def test_settings_validation():
    overrides = validate_settings('crypto', {'portfolio.weighting': 'equal', 'ml_config.training.horizon': '3'})
    assert overrides == {'universes.crypto.portfolio.weighting': 'equal', 'ml_config.training.horizon': 3}
    for bad in ({'portfolio.weighting': 'random'}, {'ml_config.models.xgboost.n_estimators': 5},
                {'tracking.database': '/tmp/x'}, {'ml_config.models.xgboost.enabled': 'no'},
                {'ml_config.models.random_forest.enabled': False, 'ml_config.models.xgboost.enabled': False,
                 'ml_config.models.neural_network.enabled': False}):
        with pytest.raises(ValueError):
            validate_settings('stocks', bad)
