"""Fast walk-forward test of stock-picking variants on real data (expanding ridge, non-overlapping holds)."""
import os, sys, pickle, warnings
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
D = os.path.dirname(os.path.abspath(__file__))
universe = sys.argv[1]; cost = float(sys.argv[2])
prepared = pickle.load(open(f'{D}/{universe}_10y.pkl', 'rb'))
close = pd.concat({s: d['Close'] for s, d in prepared.items()}, axis=1).sort_index()
feats = sorted({c for d in prepared.values() for c in d.columns if c.startswith('XS_')})
F = {f: pd.concat({s: d[f] for s, d in prepared.items() if f in d}, axis=1).reindex(index=close.index, columns=close.columns) for f in feats}
dates = close.index; syms = close.columns
ppy = 252 if universe == 'stocks' else 365

def reg(y, x):
    X = np.column_stack([np.ones(len(x)), x]); b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b; se = np.sqrt(np.diag(e @ e / (len(y) - 2) * np.linalg.inv(X.T @ X))); return b, b / se

def backtest(h, top_n, score_fn, start=600, label=''):
    fwd = close.shift(-h) / close - 1
    rows = []; prev = set()
    for i in range(start, len(dates) - h, h):
        s = score_fn(i, h)
        if s is None: continue
        ok = s.notna() & fwd.iloc[i].notna()
        if ok.sum() <= top_n: continue
        picks = set(s[ok].nlargest(top_n).index)
        turn = len(picks - prev) / top_n; prev = picks
        ic = s[ok].rank().corr(fwd.iloc[i][ok].rank())
        rows.append((dates[i], fwd.iloc[i][list(picks)].mean() - 2 * turn * cost / 1e4, fwd.iloc[i][ok].mean(), ic, turn))
    d = pd.DataFrame(rows, columns=['date', 'picks', 'univ', 'ic', 'turn']).set_index('date')
    ex = d.picks - d.univ; n = len(d); k = ppy / h
    b, t = reg(d.picks.values, d.univ.values)
    half = n // 2
    return {'variant': label, 'periods': n, 'picks %/yr': ((1 + d.picks).prod() ** (k / n) - 1) * 100,
            'universe %/yr': ((1 + d.univ).prod() ** (k / n) - 1) * 100,
            'excess t': ex.mean() / ex.std() * np.sqrt(n), 'beta': b[1], 'alpha %/yr': b[0] * k * 100, 'alpha t': t[0],
            'IC': d.ic.mean(), 'IC t': d.ic.mean() / d.ic.std() * np.sqrt(n),
            'excess 1st half %/yr': ex.iloc[:half].mean() * k * 100, 'excess 2nd half %/yr': ex.iloc[half:].mean() * k * 100,
            'turnover': d.turn.mean()}

def ridge_scorer(use, alpha=1000.0, retrain=63):
    cache = {}
    def fn(i, h):
        key = (i // retrain, h)
        if key not in cache:
            end = i - h  # labels known at decision time
            fwd = close.shift(-h) / close - 1
            tgt = fwd.sub(fwd.mean(axis=1), axis=0).rank(axis=1, pct=True) - 0.5
            X = np.column_stack([F[f].iloc[:end].values.ravel() for f in use]); y = tgt.iloc[:end].values.ravel()
            m = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
            cache[key] = Ridge(alpha=alpha).fit(X[m], y[m]) if m.sum() > 2000 else None
        model = cache[key]
        if model is None: return None
        X = np.column_stack([F[f].iloc[i].values for f in use]); ok = ~np.isnan(X).any(axis=1)
        s = pd.Series(np.nan, index=syms); s[ok] = model.predict(X[ok]); return s
    return fn

def single(f, sign=1):
    return lambda i, h: sign * F[f].iloc[i]

res = []
for h, n in (((5, 10), (5, 20), (21, 10), (21, 20)) if universe == 'stocks' else ((5, 5), (5, 10), (21, 5))):
    res.append(backtest(h, n, ridge_scorer(feats), label=f'Current model style: ridge on all features, hold {h}d, top {n}'))
mom = 'XS_mom_12_1' if 'XS_mom_12_1' in F else 'XS_mom_90'
for h, n in (((21, 10), (21, 20)) if universe == 'stocks' else ((21, 5), (5, 5))):
    res.append(backtest(h, n, single(mom), label=f'Momentum only ({mom[3:]}), hold {h}d, top {n}'))
res.append(backtest(5, 20 if universe == 'stocks' else 5, single('XS_rev_5d'), label='5-day reversal only, hold 5d, top 20'))
res.append(backtest(21, 20 if universe == 'stocks' else 5, single('XS_low_vol'), label='Low volatility only, hold 21d, top 20'))
res.append(backtest(21, 20 if universe == 'stocks' else 5, single('XS_low_vol', -1), label='HIGH volatility only, hold 21d, top 20'))
out = pd.DataFrame(res).set_index('variant')
pd.set_option('display.width', 280); pd.set_option('display.float_format', lambda v: f'{v:.2f}'); pd.set_option('display.max_colwidth', 70)
print(universe, dates[600].date(), '->', dates[-1].date(), 'cost bp', cost)
print(out.to_string())
