"""Family C: per-asset trend rule (in when price is above at least 2 of its 50/100/200-day averages), as research/rule23.py.
State from close t, position held over the return from close t+1 to close t+2. Costs on every change, by tier."""
import numpy as np, pandas as pd
from common import *

def state(p):
    votes = sum((p > p.rolling(w).mean()).astype(float) for w in (50, 100, 200))
    return (votes >= 2).where(p.rolling(200).mean().notna())

def perf(r, ppy):
    r = r.dropna(); eq = (1 + r).cumprod()
    return dict(cagr=(eq.iloc[-1] ** (ppy / len(r)) - 1) * 100, sharpe=r.mean() / r.std() * np.sqrt(ppy), dd=(eq / eq.cummax() - 1).min() * 100)

def run(u, period):
    ppy = u.rules['ppy']; s = u.close.apply(state)
    held = s.shift(2); r = u.ret
    el = u.elig.shift(2, fill_value=False)             # eligible when the state was computed
    rows = []
    for tier in (None, *TIERS):
        m = el if tier is None else el & (u.tier.shift(2) == TIERS.index(tier))
        valid = m & held.notna() & r.notna()
        w = (held == True).astype(float).where(valid)  # noqa
        n = valid.sum(axis=1).replace(0, np.nan)
        turn = w.diff().abs().fillna(0)
        rule = ((w * r).fillna(0) - turn * u.cost.shift(2) / 1e4).where(valid).sum(axis=1) / n
        hold = r.where(valid).sum(axis=1) / n
        inout = (r.where(valid & (held == True)).mean(axis=1) - r.where(valid & (held == False)).mean(axis=1))  # noqa
        keep = n.notna() & (n >= 20) & u.in_period(u.dates, period)
        rule, hold, inout = rule[keep], hold[keep], inout[keep].dropna()
        if len(rule) < 250: continue
        mo = lambda x: (1 + x).groupby(pd.Grouper(freq='ME')).prod() - 1
        rm, hm = mo(rule), mo(hold); ok = rm.index.intersection(hm.index)
        b, t = regress(rm.loc[ok].values, hm.loc[ok].values)
        a, h_ = perf(rule, ppy), perf(hold, ppy)
        rows.append({'signal': 'C trend rule (2 of 50/100/200)', 'view': tier or 'all', 'days': len(rule),
                     'rule %/yr': a['cagr'], 'hold %/yr': h_['cagr'], 'rule Sharpe': a['sharpe'], 'hold Sharpe': h_['sharpe'],
                     'rule worst drop %': a['dd'], 'hold worst drop %': h_['dd'], 'beta': b[1], 'alpha %/yr': b[0] * 12 * 100, 'alpha t': t[0],
                     'in-out %/yr': inout.mean() * ppy * 100, 'in-out t': tstat(inout.groupby(pd.Grouper(freq='ME')).mean())})
    return pd.DataFrame(rows)
