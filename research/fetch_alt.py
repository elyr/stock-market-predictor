import yfinance as yf, pandas as pd, os, warnings
warnings.filterwarnings('ignore')
D = os.path.dirname(os.path.abspath(__file__))
etfs = ['SPY','QQQ','IWM','EFA','EEM','TLT','IEF','SHY','GLD','DBC','VNQ','BIL','XLK','XLF','XLE','XLV','XLI','XLP','XLY','XLU','XLB','XLRE','XLC']
cr = ['BTC-USD','ETH-USD','SOL-USD','BNB-USD','XRP-USD','ADA-USD','DOGE-USD','LTC-USD','LINK-USD','AVAX-USD']
for name, syms in (('etf', etfs), ('crypto_long', cr)):
    d = yf.download(syms, period='max', progress=False, auto_adjust=True)['Close']
    d.to_pickle(f'{D}/{name}_close.pkl'); print(name, d.shape, d.index[0].date(), d.index[-1].date(), d.notna().sum().min())
