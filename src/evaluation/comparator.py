"""
Predicted versus actual.

Takes a *prediction log* (one row per asset per decision date: its scores, the
model's probability, and what actually happened over the horizon) and measures
how well the predictions matched reality, in ways that point at what to tune:

* **Deciles:** assets are ranked by score within each date and split into ten
  groups. A model with skill shows a staircase: the top decile does best, the
  bottom worst. Ranking happens within each date, so a good or bad week for
  the whole market does not distort the picture.
* **Calibration:** does a 60% probability come true 60% of the time?
* **IC over time:** the rank correlation between score and outcome on each
  date, and its rolling average, to see whether skill is steady or fading.
* **Breakdowns:** the same measures by sector or coin category, by market
  regime (calm, normal, turbulent) and by market direction, to see where the
  model works and where it fails.
* **Components:** IC of each score part (technical, momentum, volume, model),
  to see which parts carry signal and which add noise.

The log can come from a backtest (``Backtester`` results) or from live
predictions that have been scored (the API's track record).
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

COMPONENTS = {
    'score': 'Composite score',
    'ml_probability': 'Model',
    'technical_score': 'Technical',
    'momentum_score': 'Momentum',
    'volume_score': 'Volume',
}

LOG_COLUMNS = ['date', 'symbol', 'sector', 'score', 'rank', 'picked', 'weight', 'ml_probability',
               'technical_score', 'momentum_score', 'volume_score', 'future_return', 'universe_return',
               'excess_return', 'universe_volatility']


def normalize_log(frame: pd.DataFrame) -> pd.DataFrame:
    """Bring a backtest prediction frame or a live log into the standard column layout."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=LOG_COLUMNS)
    log = frame.rename(columns={'composite': 'score'}).copy()
    for column in LOG_COLUMNS:
        if column not in log.columns:
            log[column] = np.nan
    log['date'] = pd.to_datetime(log['date'])
    if log['excess_return'].isna().all():
        log['excess_return'] = log['future_return'] - log['universe_return']
    log['picked'] = log['picked'].fillna(False).astype(bool)
    log = log.dropna(subset=['score', 'excess_return'])
    return log[LOG_COLUMNS].sort_values(['date', 'rank']).reset_index(drop=True)


def _within_date_pct(log: pd.DataFrame, column: str) -> pd.Series:
    """Percentile rank of a score within each date (0 = worst, 1 = best)."""
    return log.groupby('date')[column].rank(pct=True, method='average')


def _safe_spearman(x: pd.Series, y: pd.Series) -> Optional[float]:
    frame = pd.DataFrame({'x': x, 'y': y}).dropna()
    if len(frame) < 5 or frame['x'].nunique() < 2 or frame['y'].nunique() < 2:
        return None
    value = spearmanr(frame['x'], frame['y'])[0]
    return None if np.isnan(value) else float(value)


def ic_by_date(log: pd.DataFrame, column: str = 'score') -> pd.Series:
    """Rank correlation between a score and the excess return on each date."""
    values = {date: _safe_spearman(group[column], group['excess_return']) for date, group in log.groupby('date')}
    return pd.Series({d: v for d, v in values.items() if v is not None}, dtype=float).sort_index()


def ic_summary(series: pd.Series) -> Dict[str, Optional[float]]:
    series = series.dropna()
    if len(series) < 2 or series.std() == 0:
        return {'mean': float(series.mean()) if len(series) else None, 't_stat': None,
                'positive_share': float((series > 0).mean()) if len(series) else None, 'periods': int(len(series))}
    return {
        'mean': float(series.mean()),
        't_stat': float(series.mean() / series.std() * np.sqrt(len(series))),
        'positive_share': float((series > 0).mean()),
        'periods': int(len(series)),
    }


def decile_table(log: pd.DataFrame, column: str = 'score', buckets: int = 10) -> Dict[str, Any]:
    """
    Average outcome by score bucket, ranking within each date.

    Uses fewer than ten buckets when there are not enough assets per date.
    Bucket 1 holds the lowest scores, the last bucket the highest.
    """
    data = log.dropna(subset=[column, 'excess_return'])
    if data.empty:
        return {'buckets': [], 'spread': None, 'monotonicity': None}
    per_date = data.groupby('date').size().median()
    n = int(max(2, min(buckets, per_date // 2)))
    pct = _within_date_pct(data, column)
    bucket = np.ceil(pct * n).clip(1, n).astype(int)
    grouped = data.assign(bucket=bucket).groupby('bucket')
    rows = [{
        'bucket': int(b),
        'mean_excess': float(g['excess_return'].mean()),
        'hit_rate': float((g['excess_return'] > 0).mean()),
        'count': int(len(g)),
    } for b, g in grouped]
    spread = rows[-1]['mean_excess'] - rows[0]['mean_excess'] if len(rows) > 1 else None
    monotonicity = _safe_spearman(pd.Series([r['bucket'] for r in rows]), pd.Series([r['mean_excess'] for r in rows])) \
        if len(rows) >= 5 else None
    return {'buckets': rows, 'spread': spread, 'monotonicity': monotonicity, 'bucket_count': n}


def calibration_table(log: pd.DataFrame, bins: int = 5) -> Dict[str, Any]:
    """Predicted probability vs how often the asset actually beat the universe."""
    data = log.dropna(subset=['ml_probability', 'excess_return'])
    if len(data) < bins * 5 or data['ml_probability'].nunique() < bins:
        return {'bins': [], 'brier': None}
    beat = (data['excess_return'] > 0).astype(float)
    groups = pd.qcut(data['ml_probability'], bins, labels=False, duplicates='drop')
    table = pd.DataFrame({'p': data['ml_probability'], 'y': beat, 'g': groups}).groupby('g')
    rows = [{'predicted': float(g['p'].mean()), 'observed': float(g['y'].mean()), 'count': int(len(g))}
            for _, g in table]
    return {'bins': rows, 'brier': float(((data['ml_probability'] - beat) ** 2).mean())}


def label_regimes(log: pd.DataFrame) -> pd.DataFrame:
    """Add market regime (by universe volatility terciles) and market direction columns."""
    data = log.copy()
    per_date = data.groupby('date').agg(vol=('universe_volatility', 'first'), ret=('universe_return', 'first'))
    if per_date['vol'].notna().sum() >= 6:
        labels = pd.qcut(per_date['vol'].rank(method='first'), 3, labels=['Calm market', 'Normal market', 'Turbulent market'])
        data['regime'] = data['date'].map(labels.astype(str))
    else:
        data['regime'] = np.nan
    direction = pd.Series(np.where(per_date['ret'] >= 0, 'Market rising', 'Market falling'), index=per_date.index)
    data['direction'] = data['date'].map(direction)
    # Rank within each date across the whole universe, so "top quintile" means the same in every group
    data['pct'] = _within_date_pct(data, 'score')
    return data


def breakdown(log: pd.DataFrame, by: str, min_count: int = 20) -> List[Dict[str, Any]]:
    """
    Skill within each group: pooled rank IC between score and excess return,
    and how the group's top-quintile assets did (ranked within each date).
    """
    data = log.dropna(subset=[by]) if by in log.columns else pd.DataFrame()
    if data.empty:
        return []
    if 'pct' not in data.columns:
        data = data.assign(pct=_within_date_pct(log, 'score').reindex(data.index))
    rows = []
    for group, g in data.groupby(by):
        if len(g) < min_count:
            continue
        top = g[g['pct'] >= 0.8]
        rows.append({
            'group': str(group),
            'count': int(len(g)),
            'ic': _safe_spearman(g['score'], g['excess_return']),
            'top_quintile_excess': float(top['excess_return'].mean()) if len(top) else None,
            'top_quintile_hit_rate': float((top['excess_return'] > 0).mean()) if len(top) else None,
            'picked_excess': float(g.loc[g['picked'], 'excess_return'].mean()) if g['picked'].any() else None,
        })
    return sorted(rows, key=lambda r: -(r['ic'] if r['ic'] is not None else -9))


def build_report(log: pd.DataFrame, rolling_window: int = 6, log_limit: int = 300) -> Dict[str, Any]:
    """
    The full predicted-versus-actual report for a prediction log.

    Returns a JSON-ready dict: summary, components, deciles, calibration,
    rolling IC, breakdowns and the most recent rows of the log.
    """
    log = normalize_log(log)
    if log.empty:
        return {'summary': {'predictions': 0, 'periods': 0}, 'components': [], 'deciles': decile_table(log),
                'calibration': {'bins': [], 'brier': None}, 'ic_series': [], 'breakdowns': {}, 'log': []}

    ic = ic_by_date(log, 'score')
    rolling = ic.rolling(rolling_window, min_periods=max(2, rolling_window // 2)).mean()
    picked = log[log['picked']]
    deciles = decile_table(log, 'score')
    top_bucket = deciles['buckets'][-1] if deciles['buckets'] else {}

    components = []
    for column, label in COMPONENTS.items():
        if column in log.columns and log[column].notna().sum() >= 20:
            components.append({'key': column, 'label': label, **ic_summary(ic_by_date(log, column)),
                               'decile_spread': decile_table(log, column)['spread']})

    labelled = label_regimes(log)
    summary = {
        'predictions': int(len(log)),
        'periods': int(log['date'].nunique()),
        'assets': int(log['symbol'].nunique()),
        'start': str(log['date'].min().date()),
        'end': str(log['date'].max().date()),
        'ic': ic_summary(ic),
        'decile_spread': deciles['spread'],
        'top_bucket_hit_rate': top_bucket.get('hit_rate'),
        'picked_count': int(len(picked)),
        'picked_mean_excess': float(picked['excess_return'].mean()) if len(picked) else None,
        'picked_hit_rate': float((picked['excess_return'] > 0).mean()) if len(picked) else None,
        'overall_hit_rate': float((log['excess_return'] > 0).mean()),
    }
    recent = log.sort_values(['date', 'rank'], ascending=[False, True]).head(log_limit)
    return {
        'summary': summary,
        'components': components,
        'deciles': deciles,
        'calibration': calibration_table(log),
        'ic_series': [{'date': str(d.date()), 'ic': float(v), 'rolling': None if pd.isna(rolling[d]) else float(rolling[d])}
                      for d, v in ic.items()],
        'breakdowns': {
            'sector': breakdown(labelled, 'sector'),
            'regime': breakdown(labelled, 'regime', min_count=10),
            'direction': breakdown(labelled, 'direction', min_count=10),
        },
        'log': [{k: (None if (isinstance(v, float) and np.isnan(v)) else v)
                 for k, v in {**row, 'date': str(row['date'].date())}.items()}
                for row in recent.to_dict(orient='records')],
    }


def headline(report: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """The few numbers used to compare experiments side by side."""
    s = report.get('summary', {})
    ic = s.get('ic') or {}
    return {
        'ic_mean': ic.get('mean'),
        'ic_t_stat': ic.get('t_stat'),
        'decile_spread': s.get('decile_spread'),
        'picked_mean_excess': s.get('picked_mean_excess'),
        'picked_hit_rate': s.get('picked_hit_rate'),
        'periods': s.get('periods'),
    }
