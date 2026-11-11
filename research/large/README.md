# Large-universe research

Scripts behind `docs/research/2026-11-large-universe.md`. Real market data (Yahoo Finance, Wikipedia index lists), not part of the app or its tests.
Caches (`*.pkl`) are ignored by git. Run from the repository root:

```bash
python3 research/large/fetch.py stocks      # S&P 500/400/600 members, 10 years (~10 min)
python3 research/large/fetch.py coins       # fixed list of ~112 coins, as far back as Yahoo has them
python3 research/large/fetch.py earnings    # earnings dates per stock (~25 min)
python3 research/large/run.py stocks dev    # development period; add holdout only after the dev results are written down
python3 research/large/run.py coins dev
python3 research/large/tables.py dev        # markdown tables and the pass list
python3 research/large/run.py stocks holdout   # run the holdout once; do not change rules afterwards
python3 research/large/run.py coins holdout
python3 research/large/tables.py holdout
```

`common.py` holds the fixed rules (eligibility, tiers, costs, split date), `xs.py` families A and B, `trend.py` family C, `earn.py` family D.
Results are written as `results_<universe>_<period>_<family>.csv`. Yahoo data changes over time; a re-run gives slightly different numbers.
