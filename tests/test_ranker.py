"""
Tests for scoring, filtering and ranking (offline, synthetic data).
"""

import numpy as np
import pandas as pd
import pytest

from src.prediction.stock_ranker import composite_score
from src.utils.helpers import recommendation_label
from conftest import SYMBOLS


@pytest.fixture(scope='module')
def recommendations(fast_config_path):
    from conftest import make_ranker
    ranker = make_ranker(fast_config_path)
    return ranker, ranker.get_top_10_recommendations(SYMBOLS, top_n=5)


def test_end_to_end_recommendations(recommendations):
    ranker, rec = recommendations
    top, full = rec['top_10'], rec['full_rankings']

    assert len(top) == 5
    assert len(full) == len(SYMBOLS)
    assert list(top['Symbol']) == list(full['Symbol'].head(5))
    assert full['Composite_Score'].is_monotonic_decreasing
    for column in ('Composite_Score', 'Technical_Score', 'ML_Score', 'Momentum_Score', 'Volume_Score'):
        assert full[column].between(0, 100).all(), column
    assert full['RSI'].notna().all(), "indicators must be computed in the real pipeline"
    assert ranker.ml_trained
    assert rec['analysis_summary']['ml_models_used']


def test_momentum_score_is_not_saturated(recommendations):
    _, rec = recommendations
    momentum = rec['full_rankings']['Momentum_Score']
    assert momentum.max() < 100
    assert momentum.nunique() > 3


def test_composite_renormalises_over_available_components():
    weights = {'a': 0.5, 'b': 0.3, 'c': 0.2}
    assert composite_score({'a': 80, 'b': 60, 'c': 40}, weights) == pytest.approx(66)
    # Missing component: average of the rest, not dragged towards zero
    assert composite_score({'a': 80, 'b': 60, 'c': None}, weights) == pytest.approx(72.5)
    assert composite_score({}, weights) == 50.0


def test_filters(ranker):
    data = ranker.fetch_and_prepare_data(['AAA'])['AAA']
    assert ranker.apply_filters('AAA', data)

    cheap = data.copy()
    cheap['Close'] = 2.0
    assert not ranker.apply_filters('AAA', cheap)

    thin = data.copy()
    thin['Volume'] = 1000
    assert not ranker.apply_filters('AAA', thin)

    assert not ranker.apply_filters('AAA', data, {'market_cap': 5e8})


def test_sentiment_disabled_is_excluded(recommendations):
    _, rec = recommendations
    assert rec['full_rankings']['Sentiment_Score'].isna().all()


def test_save_recommendations(recommendations, tmp_path):
    ranker, rec = recommendations
    path = ranker.save_recommendations(rec, str(tmp_path / 'out' / 'picks.csv'))
    saved = pd.read_csv(path)
    assert list(saved['Symbol']) == list(rec['top_10']['Symbol'])


def test_scores_on_short_history_are_neutral(ranker):
    data = ranker.fetch_and_prepare_data(['AAA'])['AAA'].head(10)
    assert ranker.calculate_momentum_score(data) == 50.0
    assert ranker.calculate_volume_score(data) == 50.0


@pytest.mark.parametrize('score,confidence,label', [
    (80, 0.8, 'STRONG BUY'), (80, 0.5, 'HOLD/WATCH'), (70, 0.65, 'BUY'), (56, 0.0, 'HOLD/WATCH'), (40, 0.9, 'AVOID'),
])
def test_recommendation_labels(score, confidence, label):
    assert recommendation_label(score, confidence) == label


def test_empty_symbol_list_raises(ranker):
    ranker.config.setdefault('stock_config', {})['symbols'] = []
    with pytest.raises(ValueError):
        ranker.get_top_10_recommendations([])
