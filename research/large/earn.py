"""Family D (stocks): earnings surprise and reaction-day terciles from past events only; excess return over an equal-weight
benchmark of eligible assets (same tier for tier rows) after a round-trip cost. Enter at close t+1 after the reaction day t.
One observation per quarter for the t-statistic. Lows are scored as a short (excess negated), borrow cost ignored."""
import numpy as np, pandas as pd, pickle
from common import *

HS = (5, 21, 60)

def events(u):
    earn = pickle.load(open(f'{D}/earnings.pkl', 'rb')); dates = u.dates; rows = []
    r = u.ret; mkt = r.where(u.elig.shift(1, fill_value=False)).mean(axis=1)
    for s, e in earn.items():
        if s not in u.close: continue
        e = e.dropna(subset=['Reported EPS', 'EPS Estimate']); c = u.close[s]
        for ts, row in e.iterrows():
            day = pd.Timestamp(ts.date()); after = ts.hour >= 16
            i = dates.searchsorted(day + pd.Timedelta(days=1) if after else day)
            if i < 61 or i >= len(dates) - 2 or (dates[i] - day).days > 5: continue
            px = c.iloc[i - 1]
            if np.isnan(px) or np.isnan(c.iloc[i]) or not u.elig[s].iloc[i - 1]: continue
            rows.append(dict(symbol=s, date=dates[i], i=i, surprise=(row['Reported EPS'] - row['EPS Estimate']) / px,
                             reaction=r[s].iloc[i] - mkt.iloc[i], tier=int(u.tier[s].iloc[i - 1])))
    return pd.DataFrame(rows).sort_values('date').reset_index(drop=True)

def run(u, period):
    ev = events(u); dates = u.dates; ppy_unused = None
    for col in ('surprise', 'reaction'):                  # terciles from earlier events only
        ev[col + '_hi'] = ev[col] > ev[col].expanding(min_periods=300).quantile(2 / 3).shift(1)
        ev[col + '_lo'] = ev[col] < ev[col].expanding(min_periods=300).quantile(1 / 3).shift(1)
    ready = ev['reaction'].expanding(min_periods=300).quantile(0.5).shift(1).notna()
    sigs = [('All events (baseline)', ready, 1), ('Surprise top third (long)', ready & ev.surprise_hi, 1),
            ('Surprise bottom third (short)', ready & ev.surprise_lo, -1), ('Reaction top third (long)', ready & ev.reaction_hi, 1),
            ('Reaction bottom third (short)', ready & ev.reaction_lo, -1),
            ('Surprise and reaction both top (long)', ready & ev.surprise_hi & ev.reaction_hi, 1),
            ('Surprise and reaction both bottom (short)', ready & ev.surprise_lo & ev.reaction_lo, -1)]
    bench = {}
    for tier in (None, *TIERS):                          # equal-weight eligible benchmark, eligibility known the day before
        m = u.view(tier).shift(1, fill_value=False)
        bench[tier] = (1 + u.ret.where(m).mean(axis=1).fillna(0)).cumprod()
    out = []
    for h in HS:
        i = ev.i.values; ok = i + 1 + h < len(dates)
        ex = pd.Series(np.nan, index=ev.index); entry = i + 1
        for tier in (None, *TIERS):
            b = bench[tier]; sel = ok.copy()
            px = np.array([u.close[s].iloc[min(j, len(dates) - 1)] for s, j in zip(ev.symbol, entry)])
            px2 = np.array([u.close[s].iloc[min(j + h, len(dates) - 1)] for s, j in zip(ev.symbol, entry)])
            bret = b.values[np.minimum(entry + h, len(dates) - 1)] / b.values[np.minimum(entry, len(dates) - 1)] - 1
            cost = np.array([u.cost[s].iloc[j - 1] for s, j in zip(ev.symbol, entry)]) * 2 / 1e4
            raw = pd.Series(px2 / px - 1 - bret, index=ev.index)
            exit_date = pd.Series(dates[np.minimum(entry + h, len(dates) - 1)], index=ev.index)
            inper = u.in_period(ev.date, period) & u.in_period(exit_date, period) & sel & raw.notna()
            tmask = inper if tier is None else inper & (ev.tier == TIERS.index(tier))
            for label, m, sign in sigs:
                x = ((sign * raw - cost)[m & tmask]).dropna(); d = ev.date[x.index]
                q = x.groupby(d.dt.to_period('Q')).mean()
                if len(x) < 30 or len(q) < 4: continue
                out.append({'signal': f'D {label}', 'view': tier or 'all', 'horizon': h, 'events': len(x),
                            'excess %': x.mean() * 100, 't': tstat(q), 'beat bench %': (x > 0).mean() * 100})
    return pd.DataFrame(out)
