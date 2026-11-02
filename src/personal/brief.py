"""
The weekly brief: what matters this week, in plain sentences.

Built only from data Ledger already has (prices, the latest analysis, the
track record, the forecasts, your portfolio and the alerts), with fixed rules
rather than a language model, so every sentence can be traced to a number and
reads the same way every week.

The brief always ends with **what to do**, and "nothing" is a valid answer:
most weeks, the right move for a long-term investor is to change nothing.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


def _pct(value: Optional[float], digits: int = 1, signed: bool = True) -> str:
    if value is None or not np.isfinite(value):
        return 'n/a'
    text = f'{value * 100:.{digits}f}%'
    return f'+{text}' if signed and value > 0 else text


def _money(value: Optional[float]) -> str:
    if value is None or not np.isfinite(value):
        return 'n/a'
    sign = '−' if value < 0 else ''
    amount = abs(value)
    return f'{sign}${amount:,.0f}' if amount >= 1000 else f'{sign}${amount:,.2f}'


def _signed_money(value: Optional[float]) -> str:
    if value is None or not np.isfinite(value):
        return 'n/a'
    return ('+' if value > 0 else '') + _money(value)


def week_moves(closes: Dict[str, pd.Series], days: int) -> pd.Series:
    """Each asset's return over the last ``days`` rows of its history."""
    moves = {}
    for symbol, close in closes.items():
        close = close.dropna()
        if len(close) > days:
            moves[symbol] = float(close.iloc[-1] / close.iloc[-1 - days] - 1)
    return pd.Series(moves, dtype=float)


def market_section(closes: Dict[str, pd.Series], days: int, names: Dict[str, str], noun: str,
                   period: str) -> Dict[str, Any]:
    moves = week_moves(closes, days)
    if moves.empty:
        return {'title': 'The market', 'lines': ['No recent prices.'], 'facts': {}}
    average = float(moves.mean())
    up_share = float((moves > 0).mean())
    best = moves.nlargest(3)
    worst = moves.nsmallest(3)
    tone = ('a strong' if average > 0.02 else 'a good' if average > 0.005 else 'a quiet' if average > -0.005
            else 'a weak' if average > -0.02 else 'a hard')
    lines = [
        f"It was {tone} {period} for {noun}: the average one moved {_pct(average)}, "
        f"and {up_share:.0%} of them rose.",
        'Best: ' + ', '.join(f"{names.get(s, s)} {_pct(v)}" for s, v in best.items()) + '. '
        'Worst: ' + ', '.join(f"{names.get(s, s)} {_pct(v)}" for s, v in worst.items()) + '.',
    ]
    # Turbulence: last month's daily swings against the previous three months
    returns = pd.DataFrame({s: c.dropna().pct_change() for s, c in closes.items()}).mean(axis=1).dropna()
    if len(returns) > 90:
        recent, before = returns.tail(21).std(), returns.iloc[-90:-21].std()
        if before > 0:
            ratio = recent / before
            if ratio > 1.3:
                lines.append('Markets have been choppier than usual over the last month: bigger swings either way.')
            elif ratio < 0.75:
                lines.append('Markets have been calmer than usual over the last month.')
    return {'title': 'The market', 'lines': lines,
            'facts': {'average': average, 'up_share': up_share, 'best': best.to_dict(), 'worst': worst.to_dict()}}


def portfolio_section(view: Optional[Dict[str, Any]], history_days: int, period: str) -> Optional[Dict[str, Any]]:
    if not view or view.get('empty') or not view.get('summary'):
        return None
    s = view['summary']
    lines: List[str] = []
    history = view.get('history') or []
    if len(history) > 1:
        # Change over the period, excluding money you added or took out
        current = history[-1]
        start = next((h for h in reversed(history[:-1]) if h['date'] <= _days_back(current['date'], history_days)),
                     history[0])
        flow = current['invested'] - start['invested']
        change = current['value'] - start['value'] - flow
        base = start['value'] or None
        if base:
            lines.append(f"Your portfolio is worth {_money(s['value'])}, {_signed_money(change)} "
                         f"({_pct(change / base)}) over the {period}, not counting money you added or took out.")
    if not lines:
        lines.append(f"Your portfolio is worth {_money(s['value'])}.")
    if s.get('vs_benchmark') is not None:
        better = s['vs_benchmark'] >= 0
        lines.append(f"Since {s['since']}, your choices are {_money(abs(s['vs_benchmark']))} "
                     f"{'ahead of' if better else 'behind'} {view['benchmark_label']} with the same money.")
    held = [p for p in view['positions'] if p['quantity'] > 0 and p.get('value')]
    if s.get('risk_label'):
        lines.append(f"Risk level: {s['risk_label'].lower()} (swings of about {_pct(s['volatility'], 0, False)} a year)."
                     + (f" Next week it will likely be worth between {_money(s['next_week']['low'])} and "
                        f"{_money(s['next_week']['high'])}." if s.get('next_week') else ''))
    return {'title': 'Your portfolio', 'lines': lines, 'warnings': view.get('warnings', []),
            'facts': {'value': s['value'], 'holdings': len(held)}}


def _days_back(day: str, days: int) -> str:
    return str((pd.Timestamp(day) - pd.Timedelta(days=days)).date())


def model_section(record: Dict[str, Any], quality: Dict[str, Any], horizon: int) -> Dict[str, Any]:
    live = (record or {}).get('live') or {}
    scored = live.get('evaluated') or 0
    lines = []
    t = quality.get('ic_t_stat')
    if t is not None:
        verdict = ('shows strong evidence of skill' if t >= 3 else 'shows some evidence of skill' if t >= 2
                   else 'is not distinguishable from luck' if t > -2 else 'has been consistently wrong')
        lines.append(f"On recent dates it never trained on, the ranking model {verdict} "
                     f"(rank IC {quality.get('ic_mean', 0):+.3f}, t = {t:.1f}).")
    if scored >= 8:
        t_live = live.get('excess_t_stat')
        lines.append(f"Live record: {scored} {horizon}-day periods scored; the picks beat the average in "
                     f"{live.get('hit_rate', 0):.0%} of them, by {_pct(live.get('avg_excess_return'), 2)} per period"
                     + (f" (t = {t_live:.1f})." if t_live is not None else '.'))
    elif scored:
        lines.append(f"Live record: only {scored} {'period' if scored == 1 else 'periods'} scored so far, "
                     f"too few to judge. It takes a few months.")
    else:
        lines.append('Live record: nothing scored yet. Predictions are checked after their holding period.')
    proven = (t is not None and t >= 2) and scored >= 8 and (live.get('excess_t_stat') or 0) >= 2
    return {'title': 'Is the model working?', 'lines': lines, 'facts': {'proven': proven, 'scored': scored}}


def ideas_section(analysis: Optional[Dict[str, Any]], ranges: Dict[str, Dict[str, float]], proven: bool,
                  count: int = 3) -> Dict[str, Any]:
    if not analysis or not analysis.get('picks'):
        return {'title': 'Ideas', 'lines': ['No analysis yet. Run one to get ideas.'], 'ideas': []}
    ideas = []
    for p in analysis['picks'][:count]:
        r = ranges.get(p['symbol'])
        ideas.append({'symbol': p['symbol'], 'name': p.get('company_name') or p['symbol'],
                      'chance': p.get('ml_probability'), 'price': p.get('current_price'),
                      'low': r['q05'] if r else None, 'high': r['q95'] if r else None})
    lines = [f"Top of the ranking: " + '; '.join(
        f"{i['symbol']} ({_pct(i['chance'], 0, False)} chance to beat the average"
        + (f", likely between ${i['low']:,.2f} and ${i['high']:,.2f} next week" if i['low'] else '') + ')'
        for i in ideas) + '.']
    lines.append('These are short-term odds slightly better than a coin flip, not certainties.' if proven else
                 'The model has not proven itself yet: treat these as a watch list, not as instructions.')
    return {'title': 'Ideas', 'lines': lines, 'ideas': ideas}


def alerts_section(alerts: List[Dict[str, Any]], held: List[str]) -> Dict[str, Any]:
    if not alerts:
        return {'title': 'Alerts', 'lines': ['No unusual moves this week.'], 'facts': {'count': 0}}
    mine = [a for a in alerts if a.get('symbol') in held]
    critical = [a for a in alerts if a.get('severity') == 'critical']
    lines = [f"{len(alerts)} unusual {'move' if len(alerts) == 1 else 'moves'} flagged this week"
             + (f", {len(critical)} of them strong" if critical else '') + '.']
    for a in (mine or critical)[:3]:
        lines.append(f"{'You hold ' + a['symbol'] + ': ' if a.get('symbol') in held else ''}{a['title']}.")
    return {'title': 'Alerts', 'lines': lines, 'facts': {'count': len(alerts), 'yours': len(mine)}}


def actions(portfolio: Optional[Dict[str, Any]], model: Dict[str, Any], analysis_age_days: Optional[int],
            alerts: Dict[str, Any]) -> List[str]:
    """What to do this week, most important first. 'Nothing' is a real answer."""
    todo: List[str] = []
    if analysis_age_days is None:
        todo.append('Run a first analysis (the button at the top) so Ledger can rank assets and forecast ranges.')
    elif analysis_age_days > 3:
        todo.append(f'The latest analysis is {analysis_age_days} days old: run a new one before acting on it.')
    if portfolio:
        for w in portfolio.get('warnings', []):
            if w['level'] == 'high':
                todo.append(w['message'])
        medium = [w for w in portfolio.get('warnings', []) if w['level'] == 'medium']
        if medium:
            todo.append(medium[0]['message'])
    if alerts['facts'].get('yours'):
        todo.append('Check the alerts on assets you hold: an unusual move is a reason to look, not necessarily to act.')
    if not model['facts'].get('proven'):
        todo.append('Do not trade on the ideas alone: the model has not shown real skill on live data yet.')
    if not todo or (len(todo) == 1 and not model['facts'].get('proven') and portfolio is not None):
        todo.append('Otherwise, nothing to do this week. Staying put is a decision too, and usually a good one.')
    return todo


def to_markdown(brief: Dict[str, Any]) -> str:
    """The brief as Markdown, to keep or send to yourself."""
    out = [f"# {brief['title']}", '', f"*{brief['subtitle']}*", '']
    for section in brief['sections']:
        out += [f"## {section['title']}", '']
        out += [line for line in section['lines']] + ['']
        for w in section.get('warnings', []) or []:
            out.append(f"- **{'Important' if w['level'] == 'high' else 'Worth a look' if w['level'] == 'medium' else 'Note'}:** {w['message']}")
        if section.get('warnings'):
            out.append('')
    out += ['## What to do', ''] + [f"{i}. {a}" for i, a in enumerate(brief['actions'], 1)] + ['']
    out += ['---', '', '_Research tool, not financial advice._', '']
    return '\n'.join(out)
