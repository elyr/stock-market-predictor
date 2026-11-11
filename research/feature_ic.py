"""Per-feature rank IC on real data, by horizon, with non-overlapping t-stats."""
import sys, os, pickle, warnings
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
universe = sys.argv[1]
prepared = pickle.load(open(f'{D}/{universe}_10y.pkl', 'rb'))
close = pd.concat({s: d['Close'] for s, d in prepared.items()}, axis=1).sort_index()
feats = sorted({c for d in prepared.values() for c in d.columns if c.startswith('XS_')})
print(universe, close.shape, close.index[0].date(), close.index[-1].date(), 'features', len(feats))
def ic_series(f, fwd):
    return f.rank(axis=1).corrwith(fwd.rank(axis=1), axis=1)  # spearman per date
rows = []
for h in (1, 5, 21):
    fwd = close.shift(-h) / close - 1
    fwd = fwd.sub(fwd.mean(axis=1), axis=0)
    for name in feats:
        f = pd.concat({s: d[name] for s, d in prepared.items() if name in d}, axis=1).reindex(close.index)
        ic = ic_series(f, fwd).dropna()
        n_ind = len(ic) / h
        t = ic.mean() / ic.std() * np.sqrt(n_ind) if ic.std() > 0 else np.nan
        # by half
        mid = len(ic) // 2
        rows.append((name[3:], h, ic.mean(), t, ic.iloc[:mid].mean(), ic.iloc[mid:].mean(), ic.iloc[-500:].mean()))
out = pd.DataFrame(rows, columns=['feature', 'h', 'ic', 't', 'ic_first_half', 'ic_second_half', 'ic_last_2y'])
pd.set_option('display.width', 200); pd.set_option('display.float_format', lambda v: f'{v:+.3f}')
for h in (1, 5, 21):
    print(f'\n--- horizon {h} days ---'); print(out[out.h == h].drop(columns='h').sort_values('t', ascending=False).to_string(index=False))
