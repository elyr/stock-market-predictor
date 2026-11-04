"""
Stored analyses and their outcomes: latest, history, scoring and the track record.

Part of :class:`api.service.UniverseService`; methods use the shared
state set up in ``core.py`` (pipeline, store, settings).
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from api.serialization import to_jsonable


class TrackRecordMixin:
    """Stored analyses and their outcomes: latest, history, scoring and the track record."""

    def latest_analysis(self) -> Optional[Dict[str, Any]]:
        run = self.store.latest_run(self.universe)
        if not run:
            return None
        return self._run_view(run)

    def run_detail(self, run_id: str) -> Optional[Dict[str, Any]]:
        run = self.store.get_run(run_id)
        if not run or run['universe'] != self.universe:
            return None
        return self._run_view(run)

    def _run_view(self, run: Dict[str, Any]) -> Dict[str, Any]:
        predictions = self.store.predictions(run['id'])
        rankings = []
        for p in predictions:
            item = dict(p['payload'])
            item.update({'rank': p['rank'], 'picked': p['picked'], 'weight': p['weight'],
                         'realized_return': p['realized_return']})
            rankings.append(item)
        summary = run.pop('summary')
        return {'run': run, 'summary': summary,
                'picks': [r for r in rankings if r['picked']], 'rankings': rankings}

    def evaluate_outcomes(self, prepared: Optional[Dict[str, pd.DataFrame]] = None) -> int:
        """
        Fill in realised results for past runs whose horizon has passed.

        Each asset's return runs from its entry close to the close ``horizon``
        rows later in its own price history.
        """
        pending = [r for r in self.store.pending_runs(self.universe) if not r['simulated']]
        if not pending:
            return 0
        if prepared is None:
            symbols = sorted({p['symbol'] for r in pending for p in self.store.predictions(r['id'])})
            raw = self.pipeline.data_collector.fetch_multiple_stocks(symbols, period='1y')
            closes = {s: d['Close'] for s, d in raw.items() if d is not None}
        else:
            closes = {s: d['Close'] for s, d in prepared.items()}

        evaluated = 0
        for run in pending:
            entry = pd.Timestamp(run['data_date'])
            horizon = int(run['horizon'])
            predictions = self.store.predictions(run['id'])
            returns, exit_dates = {}, []
            for p in predictions:
                series = closes.get(p['symbol'])
                if series is None or entry not in series.index:
                    continue
                pos = series.index.get_loc(entry)
                if pos + horizon >= len(series):
                    continue
                exit_price = series.iloc[pos + horizon]
                base = p['entry_price'] or series.iloc[pos]
                returns[p['symbol']] = float(exit_price / base - 1)
                exit_dates.append(series.index[pos + horizon])
            if len(returns) < max(2, 0.8 * len(predictions)):
                continue  # not matured yet (or data missing)

            picked = [p for p in predictions if p['picked'] and p['symbol'] in returns]
            total_weight = sum(p['weight'] or 0 for p in picked) or 1.0
            portfolio = sum((p['weight'] or 0) / total_weight * returns[p['symbol']] for p in picked)
            universe_return = float(np.mean(list(returns.values())))
            scored = [(p['composite_score'], returns[p['symbol']]) for p in predictions if p['symbol'] in returns]
            ic = float(spearmanr(*zip(*scored))[0]) if len(scored) >= 5 else None
            self.store.record_outcome(run['id'], str(max(exit_dates).date()), returns,
                                      float(portfolio), universe_return, ic)
            evaluated += 1
        return evaluated

    def track_record(self) -> Dict[str, Any]:
        """Summary of every scored run: live predictions and, in demo mode, simulated history."""
        runs = self.store.list_runs(self.universe, limit=1000)

        def summarize(items: List[Dict[str, Any]]) -> Dict[str, Any]:
            done = sorted([r for r in items if r['evaluated_at']], key=lambda r: r['data_date'])
            if not done:
                return {'evaluated': 0, 'pending': sum(1 for r in items if not r['evaluated_at'])}
            excess = np.array([r['excess_return'] for r in done])
            ics = np.array([r['rank_ic'] for r in done if r['rank_ic'] is not None])
            portfolio_curve = np.cumprod([1 + r['portfolio_return'] for r in done]) - 1
            universe_curve = np.cumprod([1 + r['universe_return'] for r in done]) - 1
            return {
                'evaluated': len(done),
                'pending': sum(1 for r in items if not r['evaluated_at']),
                'avg_excess_return': float(excess.mean()),
                'excess_t_stat': float(excess.mean() / excess.std() * np.sqrt(len(excess)))
                if len(excess) > 1 and excess.std() > 0 else None,
                'hit_rate': float((excess > 0).mean()),
                'avg_rank_ic': float(ics.mean()) if len(ics) else None,
                'curve': [{'date': r['exit_date'] or r['data_date'], 'portfolio': float(p), 'universe': float(u)}
                          for r, p, u in zip(done, portfolio_curve, universe_curve)],
            }

        counted = [r for r in runs if not r.get('superseded')]
        live = [r for r in counted if not r['simulated']]
        simulated = [r for r in counted if r['simulated']]
        return {'live': summarize(live), 'simulated': summarize(simulated), 'runs': to_jsonable(runs),
                'superseded': sum(1 for r in runs if r.get('superseded') and not r['simulated'])}

    def _record_simulated_runs(self, result) -> None:
        """Store each backtest period as a simulated, already-scored run (demo track record)."""
        if result.picks.empty:
            return
        for date, group in result.picks.groupby('date'):
            period = result.daily.loc[date]
            predictions = [{'symbol': p['symbol'], 'rank': int(p['rank']), 'picked': True,
                            'weight': float(p['weight']), 'composite_score': float(p['score']),
                            'entry_price': None, 'realized_return': float(p['return']),
                            'payload': {'symbol': p['symbol'], 'composite_score': float(p['score'])}}
                           for _, p in group.iterrows()]
            run_id = self.store.save_run(self.universe, str(date.date()), self.pipeline.horizon, len(group),
                                         {'simulated_from_backtest': True}, predictions,
                                         demo=True, simulated=True, created_at=f"{date.date()}T00:00:00+00:00")
            exit_date = date + pd.Timedelta(days=self.pipeline.horizon * (7 / 5 if self.universe == 'stocks' else 1))
            ic = period.get('composite_ic')
            self.store.record_outcome(run_id, str(exit_date.date()),
                                      {p['symbol']: p['realized_return'] for p in predictions},
                                      float(period['composite']), float(period['universe']),
                                      None if pd.isna(ic) else float(ic))
