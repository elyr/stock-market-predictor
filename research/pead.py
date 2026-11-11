"""Post-earnings drift on the app's stock universe. Enter at the close of the reaction day; no lookahead."""
import os, pickle, warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
pd.set_option('display.width', 230); pd.set_option('display.float_format', lambda v: f'{v:.2f}')
sp = pickle.load(open(f'{D}/stocks_10y.pkl', 'rb'))
close = pd.concat({s: d['Close'] for s, d in sp.items()}, axis=1).sort_index()
close.index = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
ret = close.pct_change(); mkt = ret.mean(axis=1)
earn = pickle.load(open(f'{D}/earnings.pkl', 'rb'))
dates = close.index; pos = pd.Series(np.arange(len(dates)), index=dates)
rows = []
for s, e in earn.items():
    e = e.dropna(subset=['Reported EPS', 'EPS Estimate'])
    for ts, row in e.iterrows():
        day = pd.Timestamp(ts.date()); after_close = ts.hour >= 16
        i = dates.searchsorted(day + pd.Timedelta(days=1) if after_close else day)  # reaction day index
        if i <= 0 or i >= len(dates) - 1 or (dates[i] - day).days > 5: continue
        est, act = row['EPS Estimate'], row['Reported EPS']
        px = close[s].iloc[i - 1]
        if np.isnan(px) or np.isnan(close[s].iloc[i]): continue
        rec = dict(symbol=s, date=dates[i], i=i, surprise_pct=row['Surprise(%)'], surprise_px=(act - est) / px,
                   reaction=ret[s].iloc[i] - mkt.iloc[i])
        for h in (1, 5, 21, 60):
            if i + h < len(dates):
                rec[f'fwd{h}'] = close[s].iloc[i + h] / close[s].iloc[i] - 1 - ((1 + mkt.iloc[i + 1:i + h + 1]).prod() - 1)
        rows.append(rec)
ev = pd.DataFrame(rows)
print('events', len(ev), ev.date.min().date(), '->', ev.date.max().date(), 'symbols', ev.symbol.nunique())

def summarize(mask, label, hs=(5, 21, 60)):
    out = {'signal': label, 'events': int(mask.sum())}
    for h in hs:
        x = ev.loc[mask, ['date', f'fwd{h}']].dropna()
        q = x.groupby(x.date.dt.to_period('Q'))[f'fwd{h}'].mean()      # one observation per quarter: events cluster
        out[f'{h}d excess %'] = x[f'fwd{h}'].mean() * 100
        out[f'{h}d t'] = q.mean() / q.std() * np.sqrt(len(q))
        out[f'{h}d beat mkt'] = (x[f'fwd{h}'] > 0).mean() * 100
    return out
# terciles are set from past events only (expanding), so nothing uses the future
ev = ev.sort_values('date').reset_index(drop=True)
def past_quantile(col, q):
    return ev[col].expanding(min_periods=300).quantile(q).shift(1)
for col in ('surprise_px', 'reaction'):
    ev[f'{col}_hi'] = ev[col] > past_quantile(col, 2 / 3); ev[f'{col}_lo'] = ev[col] < past_quantile(col, 1 / 3)
ready = past_quantile('reaction', 0.5).notna()
res = [summarize(ready, 'All earnings events (baseline)'),
       summarize(ready & ev.surprise_px_hi, 'Big positive EPS surprise (top third)'),
       summarize(ready & ev.surprise_px_lo, 'Big negative EPS surprise (bottom third)'),
       summarize(ready & ev.reaction_hi, 'Strong price reaction up (top third)'),
       summarize(ready & ev.reaction_lo, 'Strong price reaction down (bottom third)'),
       summarize(ready & ev.surprise_px_hi & ev.reaction_hi, 'Positive surprise AND reaction up'),
       summarize(ready & ev.surprise_px_lo & ev.reaction_lo, 'Negative surprise AND reaction down'),
       summarize(ready & ev.surprise_px_hi & ev.reaction_lo, 'Positive surprise BUT reaction down'),
       summarize(ready & ev.surprise_px_lo & ev.reaction_hi, 'Negative surprise BUT reaction up')]
print(pd.DataFrame(res).set_index('signal').to_string())
mid = ev.date.quantile(0.55)
print('\nStability of "reaction up" and "reaction down" over 21 and 60 days, by half:')
for label, m in (('reaction up', ev.reaction_hi), ('reaction down', ev.reaction_lo), ('surprise+ & reaction up', ev.surprise_px_hi & ev.reaction_hi), ('surprise- & reaction down', ev.surprise_px_lo & ev.reaction_lo)):
    a = summarize(ready & m & (ev.date < mid), '', (21, 60)); b = summarize(ready & m & (ev.date >= mid), '', (21, 60))
    print(f"  {label:26s} first half: 21d {a['21d excess %']:+.2f}% (t {a['21d t']:+.1f}), 60d {a['60d excess %']:+.2f}% (t {a['60d t']:+.1f}) | second half: 21d {b['21d excess %']:+.2f}% (t {b['21d t']:+.1f}), 60d {b['60d excess %']:+.2f}% (t {b['60d t']:+.1f})")
ev.to_pickle(f'{D}/events.pkl')
