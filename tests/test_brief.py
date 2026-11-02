"""The weekly brief: plain sentences from stored data, always ending with what to do."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.settings import Settings
from src.personal import brief as rules


def closes(trend: float, n_assets: int = 6, days: int = 120, seed: int = 0):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range('2026-01-01', periods=days)
    return {f'S{i}': pd.Series(100 * np.exp(np.cumsum(rng.normal(trend, 0.01, days))), index=index)
            for i in range(n_assets)}


def test_market_section_describes_the_week():
    good = rules.market_section(closes(0.01), 5, {}, 'stocks', 'week')
    bad = rules.market_section(closes(-0.01), 5, {}, 'stocks', 'week')
    assert 'strong' in good['lines'][0] or 'good' in good['lines'][0]
    assert 'hard' in bad['lines'][0] or 'weak' in bad['lines'][0]
    assert good['lines'][1].startswith('Best: ')


def test_model_section_is_honest_about_little_evidence():
    early = rules.model_section({'live': {'evaluated': 2}}, {'ic_mean': 0.08, 'ic_t_stat': 4.0}, 5)
    assert 'too few to judge' in ' '.join(early['lines'])
    assert early['facts']['proven'] is False
    proven = rules.model_section({'live': {'evaluated': 30, 'hit_rate': 0.6, 'avg_excess_return': 0.004,
                                           'excess_t_stat': 2.5}}, {'ic_mean': 0.05, 'ic_t_stat': 3.0}, 5)
    assert proven['facts']['proven'] is True


def test_actions_say_nothing_when_nothing_is_needed():
    model = {'facts': {'proven': True}}
    calm = rules.actions({'warnings': []}, model, 1, {'facts': {'count': 0, 'yours': 0}})
    assert len(calm) == 1 and calm[0].startswith('Otherwise, nothing to do')
    busy = rules.actions({'warnings': [{'level': 'high', 'message': 'AAA is 60% of your portfolio.'}]},
                         {'facts': {'proven': False}}, 10, {'facts': {'count': 2, 'yours': 1}})
    assert busy[0].startswith('The latest analysis is 10 days old')
    assert 'AAA is 60% of your portfolio.' in busy
    assert any('Do not trade on the ideas alone' in a for a in busy)
    two = rules.actions({'rules': {'max_position': 0.2}, 'warnings': [
        {'level': 'high', 'kind': 'position', 'symbol': 'AAA', 'message': 'AAA too big.'},
        {'level': 'high', 'kind': 'position', 'symbol': 'BBB', 'message': 'BBB too big.'}]},
        {'facts': {'proven': True}}, 1, {'facts': {'count': 0, 'yours': 0}})
    assert two[0] == 'Bring AAA and BBB back under your 20% limit per holding, by trimming them or adding other positions (see My portfolio).'
    assert 'AAA too big.' not in two


def test_markdown_has_every_section_and_the_disclaimer():
    brief = {'title': 'T', 'subtitle': 'S', 'actions': ['Nothing.'],
             'sections': [{'title': 'The market', 'lines': ['Quiet.']},
                          {'title': 'Your portfolio', 'lines': ['Fine.'], 'warnings': [{'level': 'high', 'message': 'Trim.'}]}]}
    md = rules.to_markdown(brief)
    assert '## The market' in md and '**Important:** Trim.' in md and '1. Nothing.' in md
    assert 'not financial advice' in md


@pytest.fixture
def client(fast_config_path, tmp_path):
    settings = Settings(config_path=fast_config_path, demo_mode=True, seed_demo=False,
                        database_path=str(tmp_path / 'db.sqlite'), model_registry='off')
    with TestClient(create_app(settings)) as c:
        yield c


def test_brief_api(client):
    brief = client.get('/api/stocks/brief').json()
    titles = [s['title'] for s in brief['sections']]
    assert titles[0] == 'The market' and 'Your portfolio' not in titles  # nothing recorded yet
    assert any('first analysis' in a for a in brief['actions'])
    day = (date.today() - timedelta(days=40)).isoformat()
    client.post('/api/stocks/portfolio/transactions',
                json={'symbol': 'AAPL', 'side': 'buy', 'trade_date': day, 'quantity': 5, 'price': 100})
    brief = client.get('/api/stocks/brief').json()
    assert 'Your portfolio' in [s['title'] for s in brief['sections']]
    assert any('AAPL is 100%' in a for a in brief['actions'])
    md = client.get('/api/stocks/brief.md')
    assert md.status_code == 200 and md.text.startswith('# ')
