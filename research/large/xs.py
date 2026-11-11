"""Families A and B: top-decile portfolios from a score (ridge or single input), rebalanced every h days.
Signal from close t, trade at close t+1, exit at close t+1+h. Costs on every change of weights."""
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from common import *

START_A, START_B = 600, 300       # first decision row (A needs a training history)
NAMES = ['rev_1d', 'rev_5d', 'low_vol', 'low_beta', 'z_ma20', 'high52', 'max_ret', 'vol_shock', 'rev_x_vol']

def ridge_score(u, h, period, retrain=63, alpha=1000.0):
    """Expanding-window ridge (as research/variants.py); trained only on eligible rows whose labels are known at the decision."""
    mom = ['mom_30', 'mom_90'] if u.name == 'coins' else ['mom_12_1']
    f = u.features(); use = NAMES + mom
    el = u.elig
    F = {k: gaussian_rank(f[k].where(el)).fillna(0.0).where(el) for k in use}      # ranked among eligible assets
    fwd = u.close.shift(-(1 + h)) / u.close.shift(-1) - 1
    tgt = fwd.where(el).sub(fwd.where(el).mean(axis=1), axis=0).rank(axis=1, pct=True) - 0.5
    scores, cache = {}, {}
    for i in grid(u, h, START_A, period):
        key = i // retrain
        if key not in cache:
            end = i - h                                          # label of row j is known when j+1+h <= i
            X = np.column_stack([F[k].iloc[:end].values.ravel() for k in use]).astype(np.float32); y = tgt.iloc[:end].values.ravel()
            m = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
            cache = {key: Ridge(alpha=alpha).fit(X[m], y[m]) if m.sum() > 5000 else None}
        mdl = cache[key]
        if mdl is None: continue
        X = np.column_stack([F[k].iloc[i].values for k in use]); ok = ~np.isnan(X).any(axis=1)
        s = pd.Series(np.nan, index=u.syms); s[ok] = mdl.predict(X[ok]); scores[i] = s
    return scores

def single_score(u, name, sign, h, period, start=START_B):
    f = u.features()[name] * sign
    return {i: f.iloc[i] for i in grid(u, h, start, period)}

def grid(u, h, start, period):
    """Decision rows on a fixed grid (every h rows from START_A, whatever the family) inside the period; the exit must also fall inside it."""
    out = []
    for i in range(START_A, len(u.dates) - h - 1, h):
        if i < start: continue
        d = u.dates[i]
        if not u.in_period(d, period) or not u.in_period(u.dates[i + 1 + h], period): continue
        out.append(i)
    return out

def backtest(u, scores, h, tier, min_assets=20):
    fwd = u.close.shift(-(1 + h)) / u.close.shift(-1) - 1
    mask = u.view(tier); rows = []; prev = pd.Series(dtype=float)
    for i, s in scores.items():
        ok = mask.iloc[i] & s.notna() & fwd.iloc[i].notna()
        if ok.sum() < min_assets: prev = pd.Series(dtype=float); continue
        n = max(2, int(round(0.1 * ok.sum())))
        picks = s[ok].nlargest(n).index
        w = pd.Series(1.0 / n, index=picks)
        allw = pd.concat([w, prev]).groupby(level=0).sum() if len(prev) else w
        dw = (w.reindex(allw.index).fillna(0) - prev.reindex(allw.index).fillna(0)).abs()
        cost = float((dw * u.cost.iloc[i].reindex(allw.index)).sum()) / 1e4
        turn = float(len(set(picks) - set(prev.index)) / n)
        ic = s[ok].rank().corr(fwd.iloc[i][ok].rank())
        rows.append((u.dates[i], fwd.iloc[i][picks].mean() - cost, fwd.iloc[i][ok].mean(), ic, turn)); prev = w
    if len(rows) < 6: return None
    d = pd.DataFrame(rows, columns=['date', 'picks', 'bench', 'ic', 'turn']).set_index('date')
    n, k = len(d), u.rules['ppy'] / h
    b, t = regress(d.picks.values, d.bench.values)
    ann = lambda r: ((1 + r).prod() ** (k / n) - 1) * 100
    return {'periods': n, 'picks %/yr': ann(d.picks), 'bench %/yr': ann(d.bench), 'beta': b[1],
            'alpha %/yr': b[0] * k * 100, 'alpha t': t[0], 'IC': d.ic.mean(), 'IC t': tstat(d.ic), 'turnover': d.turn.mean()}

def run(u, period):
    """All A and B tables for one universe and period; returns a DataFrame with one row per signal x view."""
    rows = []
    sigs = []
    for h in (5, 21): sigs.append((f'A ridge, top decile, hold {h}d', h, lambda h=h: ridge_score(u, h, period)))
    mom = ('mom_90', 90) if u.name == 'coins' else ('mom_12_1', 12)
    sigs += [(f'B {"90-day" if u.name == "coins" else "12-1 month"} momentum, hold 21d', 21, lambda: single_score(u, mom[0], 1, 21, period)),
             ('B low volatility, hold 21d', 21, lambda: single_score(u, 'low_vol', 1, 21, period)),
             ('B 5-day reversal, hold 5d', 5, lambda: single_score(u, 'rev_5d', 1, 5, period))]
    for label, h, fn in sigs:
        sc = fn()
        for tier in (None, *TIERS):
            r = backtest(u, sc, h, tier)
            if r: rows.append({'signal': label, 'view': tier or 'all', **r})
        print(u.name, period, label, flush=True)
    return pd.DataFrame(rows)
