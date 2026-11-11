import os, warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
from scipy import stats as st
D = os.path.dirname(os.path.abspath(__file__))
c = pd.read_pickle(f'{D}/crypto_long_close.pkl'); e = pd.read_pickle(f'{D}/etf_close.pkl')
pd.set_option('display.width', 220); pd.set_option('display.float_format', lambda v: f'{v:.2f}')
def perf(r, ppy):
    r = r.dropna(); eq = (1 + r).cumprod()
    return eq.iloc[-1] ** (ppy / len(r)) - 1, r.mean() / r.std() * np.sqrt(ppy), (eq / eq.cummax() - 1).min()
print('1) Next-day return when the price is above vs below its average (is the difference real?)')
rows = []
for name, p, ppy in (('BTC', c['BTC-USD'].dropna(), 365), ('ETH', c['ETH-USD'].dropna(), 365), ('SOL', c['SOL-USD'].dropna(), 365), ('SPY', e['SPY'].dropna(), 252), ('QQQ', e['QQQ'].dropna(), 252)):
    r = p.pct_change().shift(-1)
    for n in (50, 100, 200):
        above = p > p.rolling(n).mean(); valid = p.rolling(n).mean().notna() & r.notna()
        a, b = r[valid & above], r[valid & ~above]
        t = st.ttest_ind(a, b, equal_var=False).statistic
        rows.append((name, n, f'{above[valid].mean():.0%}', a.mean() * ppy * 100, b.mean() * ppy * 100, a.std() * np.sqrt(ppy) * 100, b.std() * np.sqrt(ppy) * 100, t))
print(pd.DataFrame(rows, columns=['asset', 'avg days', 'time above', 'ann. return above %', 'ann. return below %', 'vol above %', 'vol below %', 't of difference']).to_string(index=False))
print('\n2) BTC: every window from 20 to 250 days (15 bp per trade), since 2015')
p = c['BTC-USD'].dropna(); r = p.pct_change(); start = p.index[250]
bh = perf(r.loc[start:], 365); res = []
for n in range(20, 251, 10):
    sig = (p > p.rolling(n).mean()).astype(float).shift(1)
    s = (sig * r - sig.diff().abs() * 0.0015).loc[start:]
    res.append((n, *perf(s, 365), int(sig.diff().abs().loc[start:].sum() / ((len(s)) / 365))))
t = pd.DataFrame(res, columns=['window', 'CAGR', 'Sharpe', 'MaxDD', 'trades/yr'])
print(f'buy and hold: CAGR {bh[0]:.0%}, Sharpe {bh[1]:.2f}, max drawdown {bh[2]:.0%}')
print(f'trend rule over {len(t)} windows: Sharpe min {t.Sharpe.min():.2f} / median {t.Sharpe.median():.2f} / max {t.Sharpe.max():.2f}; '
      f'max drawdown best {t.MaxDD.max():.0%} / median {t.MaxDD.median():.0%} / worst {t.MaxDD.min():.0%}; '
      f'CAGR min {t.CAGR.min():.0%} / median {t.CAGR.median():.0%} / max {t.CAGR.max():.0%}; windows beating buy-and-hold Sharpe: {(t.Sharpe > bh[1]).sum()}/{len(t)}; trades/yr median {t["trades/yr"].median():.0f}')
print('\n3) Last 12 months (the year the crypto picks lost 36%)')
for sym in ('BTC-USD', 'ETH-USD', 'SOL-USD'):
    p = c[sym].dropna(); r = p.pct_change(); a = p.index[-365]
    out = [f'{sym}: buy and hold {(1 + r.loc[a:]).prod() - 1:+.0%}']
    for n in (50, 100, 200):
        sig = (p > p.rolling(n).mean()).astype(float).shift(1); s = (sig * r - sig.diff().abs() * 0.0015).loc[a:]
        out.append(f'{n}d rule {(1 + s).prod() - 1:+.0%}')
    print(', '.join(out), '| now:', 'ABOVE' if p.iloc[-1] > p.rolling(100).mean().iloc[-1] else 'BELOW', 'its 100-day average')
