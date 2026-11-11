"""Shared panels, point-in-time eligibility, size tiers and costs. All rules are fixed in advance (see the note)."""
import os, sys, pickle, warnings
warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
from src.models.cross_section import raw_features, gaussian_rank
D = os.path.dirname(os.path.abspath(__file__))
SPLIT = pd.Timestamp('2024-11-10')                       # development ends here; holdout starts the next day
RULES = {'stocks': dict(min_dv=5e6, min_px=2.0, ppy=252, cost=(5, 15, 40)),
         'coins': dict(min_dv=10e6, min_px=0.0, ppy=365, cost=(15, 40, 100))}
TIERS = ('large', 'mid', 'small')

class Universe:
    def __init__(self, name):
        self.name, self.rules = name, RULES[name]
        raw = pickle.load(open(f'{D}/{name}.pkl', 'rb'))
        c = raw['close'].sort_index(); v = raw['volume'].reindex(index=c.index, columns=c.columns)
        c.index = pd.DatetimeIndex(c.index).tz_localize(None).normalize(); v.index = c.index
        c = c[~c.index.duplicated()]; v = v[~v.index.duplicated()]
        c = c.where(c > 0)
        self.close, self.volume, self.dates, self.syms = c, v, c.index, c.columns
        dv = c * v if name == 'stocks' else v            # Yahoo reports coin volume in US dollars already
        self.med_dv = dv.rolling(60, min_periods=40).median()
        self.elig = (self.med_dv >= self.rules['min_dv']) & (c >= self.rules['min_px']) & c.notna()
        t = np.where(self.med_dv >= 100e6, 0, np.where(self.med_dv >= 20e6, 1, 2))
        self.tier = pd.DataFrame(t, index=c.index, columns=c.columns)
        self.cost = self.tier.replace({i: b for i, b in enumerate(self.rules['cost'])}).astype(float)   # one-way bp
        self.ret = c.pct_change(fill_method=None)

    def view(self, tier=None):
        """Eligibility mask for 'all' (tier None) or one size tier, at each date."""
        return self.elig if tier is None else self.elig & (self.tier == TIERS.index(tier))

    def features(self):
        if hasattr(self, '_f'): return self._f
        kw = dict(market='BTC-USD', momentum='short', year=365) if self.name == 'coins' else dict(momentum='long', year=252)
        f, _ = raw_features(self.close, self.volume, **kw)
        self._f = f; return f

    def in_period(self, d, period):
        return (d <= SPLIT) if period == 'dev' else (d > SPLIT)

def tstat(x):
    x = pd.Series(x).dropna()
    return float(x.mean() / x.std() * np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else np.nan

def regress(y, x):
    X = np.column_stack([np.ones(len(x)), x]); b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b; se = np.sqrt(np.diag(e @ e / (len(y) - 2) * np.linalg.inv(X.T @ X))); return b, b / se
