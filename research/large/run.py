"""python3 research/large/run.py <stocks|coins> <dev|holdout> [A|B|C|D ...]: writes results_<universe>_<period>.csv"""
import sys, time
import pandas as pd
from common import *
import xs, trend, earn
uni, period = sys.argv[1], sys.argv[2]; fam = sys.argv[3:] or ['AB', 'C', 'D']
u = Universe(uni); out = []
print(uni, period, 'assets', u.close.shape[1], u.dates[0].date(), u.dates[-1].date(), flush=True)
e = u.elig
print('eligible per day (median):', int(e.sum(axis=1).median()), 'last:', int(e.iloc[-1].sum()), flush=True)
t0 = time.time()
if 'AB' in fam: out.append(('AB', xs.run(u, period))); print('AB', time.time() - t0, flush=True)
if 'C' in fam: out.append(('C', trend.run(u, period))); print('C', flush=True)
if 'D' in fam and uni == 'stocks': out.append(('D', earn.run(u, period)))
for name, df in out: df.to_csv(f'{D}/results_{uni}_{period}_{name}.csv', index=False)
print('done')
