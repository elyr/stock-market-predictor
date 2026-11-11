"""Turn results_*.csv into markdown tables and the pass list: python3 research/large/tables.py <dev|holdout>"""
import sys, os, pandas as pd
D = os.path.dirname(os.path.abspath(__file__)); period = sys.argv[1]
def md(df):
    df = df.copy()
    for c in df.columns:
        if df[c].dtype.kind == 'f': df[c] = df[c].map(lambda v: f'{v:.2f}')
    return '| ' + ' | '.join(df.columns) + ' |\n|' + '---|' * len(df.columns) + '\n' + '\n'.join('| ' + ' | '.join(map(str, r)) + ' |' for r in df.values)
def load(uni):
    parts = {n: pd.read_csv(f'{D}/results_{uni}_{period}_{n}.csv') for n in ('AB', 'C', 'D') if os.path.exists(f'{D}/results_{uni}_{period}_{n}.csv')}
    return parts
def key(df):  # the one number each family is judged on
    d = df.copy(); d['stat'] = d['alpha t'] if 'alpha t' in d else d['t']; d['effect'] = d['alpha %/yr'] if 'alpha %/yr' in d else d['excess %']
    d['id'] = d.signal + (' h' + d.horizon.astype(str) if 'horizon' in d else '') + ' [' + d.view + ']'
    return d[['id', 'effect', 'stat']]
if __name__ == '__main__':
    n = 0; allk = []
    for uni in ('stocks', 'coins'):
        p = load(uni); print(f'\n## {uni} ({period})\n')
        for name, df in p.items():
            print(f'### {name}\n'); 
            for v in ('all', 'large', 'mid', 'small'):
                s = df[df.view == v].drop(columns='view')
                if len(s): print(f'**{v}**\n\n{md(s)}\n')
            k = key(df); k['universe'] = uni; allk.append(k); n += len(k)
    k = pd.concat(allk); k.to_csv(f'{D}/keys_{period}.csv', index=False)
    print(f'\nTests: {n}; passing (effect>0 and t>=3):\n'); print(md(k[(k.effect > 0) & (k.stat >= 3)]))
