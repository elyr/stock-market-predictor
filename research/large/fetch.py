"""Download and cache prices (stocks, coins) and earnings dates. Run from anywhere: python3 research/large/fetch.py [stocks|coins|earnings]."""
import io, os, sys, time, pickle, warnings
warnings.filterwarnings('ignore')
import pandas as pd, requests, yfinance as yf
D = os.path.dirname(os.path.abspath(__file__))
PAGES = {'sp500': 'List_of_S%26P_500_companies', 'sp400': 'List_of_S%26P_400_companies', 'sp600': 'List_of_S%26P_600_companies'}
# Coins that were in the top 100 by market value at some year-end 2017-2024, including ones that later collapsed.
COINS = ('BTC ETH XRP BCH LTC ADA XLM MIOTA NEO XMR DASH EOS XEM TRX ETC VET BNB QTUM OMG LSK ZEC USDT BTG ICX '
         'STEEM XVG BTS ONT NANO WAVES ZIL DOGE LINK DOT UNI SOL MATIC LUNA1 FTT AVAX ATOM ALGO XTZ CRO THETA FIL '
         'AAVE EGLD SUSHI COMP MKR SNX YFI CAKE RUNE KSM NEAR FTM SAND MANA AXS GALA APE SHIB HBAR ICP FLOW CHZ ENJ '
         'BAT ZRX REP KNC OKB HT LEO XDC BSV KCS HOT RVN DGB SC BTT CELO ONE KAVA CRV 1INCH GRT LRC AR STX ZEN IOST '
         'WAXP ANKR AMP MINA APT ARB OP INJ SUI RNDR IMX LDO TIA SEI PEPE').split()
# Yahoo's own tickers for coins whose plain '<SYMBOL>-USD' page is missing (tried when the plain one has no data).
ALT = {'MIOTA': 'IOTA-USD', 'NANO': 'XNO-USD', 'UNI': 'UNI7083-USD', 'MATIC': 'POL28321-USD', 'LUNA1': 'LUNA20314-USD',
       'COMP': 'COMP5692-USD', 'FTM': 'S-USD', 'GRT': 'GRT6719-USD', 'STX': 'STX4847-USD', 'APT': 'APT21794-USD',
       'SUI': 'SUI20947-USD', 'RNDR': 'RENDER-USD', 'IMX': 'IMX10603-USD', 'PEPE': 'PEPE24478-USD', 'GALA': 'GALA-USD'}
SPECIAL = {}
# Yahoo has only some of the dead coins under other tickers; LUNC (the collapsed Terra Classic) is added alongside.
COINS += ['LUNC', 'UST']

def stock_symbols():
    out = {}
    for tier, page in PAGES.items():
        html = requests.get(f'https://en.wikipedia.org/wiki/{page}', headers={'User-Agent': 'Mozilla/5.0 research'}, timeout=60).text
        t = [x for x in pd.read_html(io.StringIO(html)) if 'Symbol' in x.columns or 'Ticker symbol' in x.columns][0]
        col = 'Symbol' if 'Symbol' in t.columns else 'Ticker symbol'
        for s in t[col].astype(str): out[s.strip().replace('.', '-')] = tier
    return out

def download(syms, batch=50):
    close, vol, missing = {}, {}, []
    for i in range(0, len(syms), batch):
        b = syms[i:i + batch]
        for attempt in range(3):
            try:
                d = yf.download(b, period='10y', progress=False, auto_adjust=True, threads=True)
                break
            except Exception as e:
                time.sleep(5)
        else: missing += b; continue
        for s in b:
            try:
                c, v = d['Close'][s].dropna(), d['Volume'][s]
                if len(c) > 250: close[s] = c; vol[s] = v.reindex(c.index)
                else: missing.append(s)
            except Exception: missing.append(s)
        print(i, len(close), flush=True); time.sleep(1)
    return pd.DataFrame(close).sort_index(), pd.DataFrame(vol).sort_index(), missing

def main(what):
    if what == 'stocks':
        sy = stock_symbols(); print('constituents', len(sy))
        c, v, miss = download(sorted(sy))
        pickle.dump(dict(close=c, volume=v, missing=miss, source=sy), open(f'{D}/stocks.pkl', 'wb'))
        print('stocks', c.shape, 'missing', len(miss))
    elif what == 'coins':
        syms = [f'{s}-USD' if s not in SPECIAL else SPECIAL[s] for s in dict.fromkeys(COINS)]
        close, vol, miss = {}, {}, []
        for s in syms:  # one by one, with the longest history available
            base = s[:-4]
            for cand in (s, ALT.get(base)):
                if not cand: continue
                try:
                    d = yf.download(cand, period='max', progress=False, auto_adjust=True)
                    if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
                    d = d[d['Close'].notna()]
                    if len(d) > 250: close[s] = d['Close']; vol[s] = d['Volume']; break
                except Exception: pass
            else: miss.append(s)
            time.sleep(0.3)
        c, v = pd.DataFrame(close).sort_index(), pd.DataFrame(vol).sort_index()
        pickle.dump(dict(close=c, volume=v, missing=miss), open(f'{D}/coins.pkl', 'wb'))
        print('coins', c.shape, 'missing', miss)
    elif what == 'earnings':
        syms = list(pickle.load(open(f'{D}/stocks.pkl', 'rb'))['close'].columns)
        path = f'{D}/earnings.pkl'; out = pickle.load(open(path, 'rb')) if os.path.exists(path) else {}
        fail = []
        for k, s in enumerate(syms):
            if s in out: continue
            for attempt in range(2):
                try:
                    e = yf.Ticker(s).get_earnings_dates(limit=60)
                    if e is not None and len(e): out[s] = e; break
                except Exception: time.sleep(2)
            else: fail.append(s)
            time.sleep(0.3)
            if k % 100 == 0: pickle.dump(out, open(path, 'wb')); print(k, len(out), flush=True)
        pickle.dump(out, open(path, 'wb')); print('earnings', len(out), 'failed', len(fail))

if __name__ == '__main__': main(sys.argv[1])
