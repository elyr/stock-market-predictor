"""Canonical trend-following rules on real data. Signal at close t, traded at close t+1. Costs charged on turnover."""
import os, warnings
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
pd.set_option('display.width', 220); pd.set_option('display.float_format', lambda v: f'{v:.2f}')

def stats(r, ppy):
    r = r.dropna(); eq = (1 + r).cumprod(); yrs = len(r) / ppy
    cagr = eq.iloc[-1] ** (1 / yrs) - 1; vol = r.std() * np.sqrt(ppy)
    dd = (eq / eq.cummax() - 1).min()
    return dict(CAGR=cagr * 100, Vol=vol * 100, Sharpe=r.mean() / r.std() * np.sqrt(ppy), MaxDD=dd * 100, Years=yrs)

def run(weights, rets, cost_bps):
    """weights decided at close t apply from t+1 (already lagged by caller's shift)."""
    w = weights.shift(1).fillna(0)
    turnover = w.diff().abs().sum(axis=1).fillna(0)
    return (w * rets).sum(axis=1) - turnover * cost_bps / 1e4

def table(named, ppy, splits):
    rows = {}
    for name, r in named.items():
        s = stats(r, ppy); row = {k: s[k] for k in ('CAGR', 'Vol', 'Sharpe', 'MaxDD')}
        for label, (a, b) in splits.items():
            seg = r.loc[a:b]
            if len(seg) > ppy: row[f'CAGR {label}'] = stats(seg, ppy)['CAGR']; row[f'DD {label}'] = stats(seg, ppy)['MaxDD']
        rows[name] = row
    print(pd.DataFrame(rows).T.to_string())

# ------------------------------------------------------------------ crypto
c = pd.read_pickle(f'{D}/crypto_long_close.pkl')
print('=== CRYPTO: hold only when price is above its moving average, else cash (15 bp per trade) ===')
for sym in ('BTC-USD', 'ETH-USD'):
    p = c[sym].dropna(); r = p.pct_change()
    named = {f'{sym} buy and hold': r}
    for n in (50, 100, 200):
        sig = (p > p.rolling(n).mean()).astype(float)
        named[f'{sym} above {n}d average'] = run(sig.to_frame(sym), r.to_frame(sym), 15)
    start = p.index[200]
    named = {k: v.loc[start:] for k, v in named.items()}
    print(f'\n{sym} from {start.date()}')
    table(named, 365, {'to 2020': (None, '2020-12-31'), '2021-23': ('2021-01-01', '2023-12-31'), '2024+': ('2024-01-01', None)})

# basket: equal weight of the coins above their 100d average (cash for the rest)
coins = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'XRP-USD', 'ADA-USD', 'DOGE-USD', 'LTC-USD', 'LINK-USD', 'AVAX-USD']
p = c[coins].loc['2018-01-01':]; r = p.pct_change()
avail = p.notna()
bh_w = avail.div(avail.sum(axis=1), axis=0)
named = {'10 coins equal weight, buy and hold': run(bh_w, r.fillna(0), 15)}
for n in (50, 100, 200):
    above = (p > p.rolling(n).mean()) & avail
    named[f'coins above {n}d average (1/N each, rest cash)'] = run(above.div(avail.sum(axis=1), axis=0), r.fillna(0), 15)
print('\nBasket of 10 large coins from 2018')
table({k: v.loc['2018-08-01':] for k, v in named.items()}, 365, {'to 2020': (None, '2020-12-31'), '2021-23': ('2021-01-01', '2023-12-31'), '2024+': ('2024-01-01', None)})

# --------------------------------------------------------------------- ETFs
e = pd.read_pickle(f'{D}/etf_close.pkl')
m = e.resample('ME').last(); mr = m.pct_change()
print('\n=== ETFs, monthly, 5 bp per trade ===')
assets = ['SPY', 'EFA', 'IEF', 'GLD', 'VNQ']
start = '2005-06-30'
mm = m[assets]; rr = mr[assets]
named = {'SPY buy and hold': mr['SPY'], '60/40 SPY/IEF': 0.6 * mr['SPY'] + 0.4 * mr['IEF'],
         '5 assets equal weight': rr.mean(axis=1)}
sig = (mm > mm.rolling(10).mean()).astype(float) / len(assets)
named['5 assets, each held only above its 10-month average (Faber)'] = run(sig, rr, 5)
# dual momentum (Antonacci): SPY if 12m return > BIL's and > EFA's; EFA if EFA best and > BIL; else IEF
r12 = m.pct_change(12)
choice = pd.DataFrame(0.0, index=m.index, columns=['SPY', 'EFA', 'IEF'])
for d in m.index:
    s, f, b = r12.at[d, 'SPY'], r12.at[d, 'EFA'], r12.at[d, 'BIL'] if not np.isnan(r12.at[d, 'BIL']) else 0.0
    if np.isnan(s) or np.isnan(f): continue
    pick = ('SPY' if s >= f else 'EFA') if max(s, f) > b else 'IEF'
    choice.at[d, pick] = 1.0
named['Dual momentum: best of SPY/EFA over 12 months, else bonds'] = run(choice, mr[['SPY', 'EFA', 'IEF']], 5)
# sector momentum: top 3 of 9 original sector ETFs by 12-month return, only if above 10-month average
sec = ['XLK', 'XLF', 'XLE', 'XLV', 'XLI', 'XLP', 'XLY', 'XLU', 'XLB']
rk = r12[sec].rank(axis=1, ascending=False)
top = ((rk <= 3) & (m[sec] > m[sec].rolling(10).mean())).astype(float) / 3
named['Top 3 sectors by 12-month return, with trend filter'] = run(top, mr[sec], 5)
named = {k: v.loc[start:] for k, v in named.items()}
table(named, 12, {'2005-12': (None, '2012-12-31'), '2013-19': ('2013-01-01', '2019-12-31'), '2020+': ('2020-01-01', None)})
