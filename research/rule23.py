import os, pickle, warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
pd.set_option('display.width', 220); pd.set_option('display.float_format', lambda v: f'{v:.2f}')
def state(p, windows=(50, 100, 200), need=2):
    votes = sum((p > p.rolling(w).mean()).astype(float) for w in windows)
    return (votes >= need).where(p.rolling(max(windows)).mean().notna())
def perf(r, ppy):
    r = r.dropna(); eq = (1 + r).cumprod()
    return dict(cagr=(eq.iloc[-1] ** (ppy / len(r)) - 1) * 100, sharpe=r.mean() / r.std() * np.sqrt(ppy), dd=(eq / eq.cummax() - 1).min() * 100)
def study(close, ppy, cost, label):
    close = close.dropna(how='all'); r = close.pct_change()
    s = close.apply(state)                         # True/False/NaN
    held = s.shift(1)                              # act the next day
    valid = held.notna() & r.notna()
    w_rule = (held == True).astype(float).where(valid)   # noqa
    n = valid.sum(axis=1).replace(0, np.nan)
    turn = w_rule.diff().abs()
    rule = ((w_rule * r) - turn.fillna(0) * cost / 1e4).sum(axis=1) / n
    hold = r.where(valid).sum(axis=1) / n
    rule, hold = rule[n.notna()], hold[n.notna()]
    diff_in_out = (r.where(valid & (held == True)).mean(axis=1) - r.where(valid & (held == False)).mean(axis=1)).dropna()  # noqa
    # Newey-West-ish: block t on monthly means
    m = diff_in_out.groupby(pd.Grouper(freq='ME')).mean().dropna()
    a, b = perf(rule, ppy), perf(hold, ppy)
    trades = turn.sum().sum() / valid.sum().sum() * ppy
    print(f"{label}: {close.shape[1]} assets, {rule.index[0].date()} -> {rule.index[-1].date()}")
    print(f"  rule:  {a['cagr']:.0f}%/yr, sharpe {a['sharpe']:.2f}, worst drop {a['dd']:.0f}%   | hold all: {b['cagr']:.0f}%/yr, sharpe {b['sharpe']:.2f}, worst drop {b['dd']:.0f}%")
    print(f"  in-trend minus out-of-trend return: {diff_in_out.mean() * ppy * 100:+.0f}%/yr, t (monthly blocks) {m.mean() / m.std() * np.sqrt(len(m)):+.2f}; trades per asset per year {trades:.1f}; time in trend {(held == True).sum().sum() / valid.sum().sum():.0%}")  # noqa
    for a0, a1 in (('2015', '2019'), ('2020', '2022'), ('2023', '2026')):
        x, y = rule.loc[a0:a1], hold.loc[a0:a1]
        if len(x) > 200: print(f"    {a0}-{a1}: rule {perf(x, ppy)['cagr']:+.0f}%/yr (drop {perf(x, ppy)['dd']:.0f}%) vs hold {perf(y, ppy)['cagr']:+.0f}%/yr (drop {perf(y, ppy)['dd']:.0f}%)")
c = pd.read_pickle(f'{D}/crypto_long_close.pkl')
study(c[['BTC-USD']], 365, 15, 'BTC')
study(c, 365, 15, '10 large coins')
cp = pickle.load(open(f'{D}/crypto_10y.pkl', 'rb'))
study(pd.concat({s: d['Close'] for s, d in cp.items()}, axis=1), 365, 15, 'App crypto universe')
sp = pickle.load(open(f'{D}/stocks_10y.pkl', 'rb'))
study(pd.concat({s: d['Close'] for s, d in sp.items()}, axis=1), 252, 5, 'App stock universe')
e = pd.read_pickle(f'{D}/etf_close.pkl')
study(e[['SPY']], 252, 5, 'SPY since 1993')
