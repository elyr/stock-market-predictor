"""Backtest the current model on real prices. Caches prepared data."""
import sys, os, pickle, warnings, logging
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT); os.chdir(ROOT)
warnings.filterwarnings('ignore'); logging.disable(logging.WARNING)
import pandas as pd
from src.prediction import create_pipeline
from src.backtest import Backtester
D = os.path.dirname(os.path.abspath(__file__))
universe, period, days = sys.argv[1], sys.argv[2], int(sys.argv[3])
cost = float(sys.argv[4]) if len(sys.argv) > 4 else None
ranker = create_pipeline(universe)
cache = f'{D}/{universe}_{period}.pkl'
if os.path.exists(cache):
    prepared = pickle.load(open(cache, 'rb'))
else:
    prepared = ranker.fetch_and_prepare_data(ranker.symbols, period=period)
    pickle.dump(prepared, open(cache, 'wb'))
print(universe, 'assets', len(prepared), 'rows', max(len(d) for d in prepared.values()),
      'from', min(d.index[0] for d in prepared.values()).date(), 'to', max(d.index[-1] for d in prepared.values()).date())
tester = Backtester.from_config(ranker, test_days=days, cost_bps=cost)
r = tester.run(prepared)
pd.set_option('display.width', 250); pd.set_option('display.float_format', lambda v: f'{v:.3f}')
print(r.settings)
print(r.metrics.to_string())
print(pd.DataFrame(r.ic).T.to_string())
pickle.dump(r, open(f'{D}/result_{universe}_{days}.pkl', 'wb'))
