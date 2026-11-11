import os, pickle, time, warnings; warnings.filterwarnings('ignore')
import yfinance as yf, pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
syms = list(pickle.load(open(f'{D}/stocks_10y.pkl', 'rb')).keys())
out, fail = {}, []
for i, s in enumerate(syms):
    for attempt in range(2):
        try:
            e = yf.Ticker(s).get_earnings_dates(limit=60)
            if e is not None and len(e): out[s] = e; break
        except Exception as ex:
            time.sleep(2)
    else: fail.append(s)
    time.sleep(0.3)
pickle.dump(out, open(f'{D}/earnings.pkl', 'wb'))
n = sum(len(e.dropna(subset=['Reported EPS'])) for e in out.values())
print('symbols', len(out), 'failed', fail, 'events with results', n)
