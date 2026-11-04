"""
Price ranges: refresh, score once prices exist, backfill, and the Forecast page.

Part of :class:`api.service.UniverseService`; methods use the shared
state set up in ``core.py`` (pipeline, store, settings).
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from api.jobs import Job
from api.serialization import to_jsonable
from src.models.forecast import RangeForecaster, horizon_labels, horizons_for, inside, reliability


class ForecastsMixin:
    """Price ranges: refresh, score once prices exist, backfill, and the Forecast page."""

    def _forecaster(self) -> RangeForecaster:
        """The range model with this universe's horizons (``forecast_horizons`` in the config adds or replaces some)."""
        ppy = self.pipeline.periods_per_year
        overrides = self.pipeline.universe_config.get('forecast_horizons') or {}
        return RangeForecaster(periods_per_year=ppy, horizons=horizons_for(ppy, overrides))

    def refresh_forecasts(self, job: Optional[Job] = None,
                          prepared: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, Any]:
        """
        Fit the range model on this universe's history, store the ranges from
        the latest prices, and score earlier ranges whose window has passed.
        """
        if job:
            job.message = f'Fetching {self.pipeline.label} prices'
        closes = self._closes(prepared)
        if not closes:
            raise RuntimeError('No prices available')
        if job:
            job.message = 'Scoring earlier forecasts'
        scored = self.evaluate_forecasts(closes)
        if job:
            job.message = 'Forecasting price ranges'
        forecaster = self._forecaster()
        evaluation = forecaster.fit(closes)
        rows = forecaster.predict(closes)
        if not rows:
            raise RuntimeError('Not enough history to forecast')
        base_date = max(r['base_date'] for r in rows)
        summary = to_jsonable({
            'method': 'Volatility ranges with conformal calibration',
            'horizons': forecaster.horizons,
            'labels': horizon_labels(self.pipeline.periods_per_year, forecaster.horizons),
            'evaluation': evaluation, 'quantiles': forecaster.quantiles, 'assets': len(closes),
        })
        batch_id = self.store.save_forecast_batch(self.universe, base_date, summary, rows)
        return {'batch_id': batch_id, 'forecasts': len(rows), 'scored': scored}

    def evaluate_forecasts(self, closes: Dict[str, pd.Series]) -> int:
        """Record the outcome of every live forecast whose window has passed."""
        scored = 0
        for f in self.store.open_forecasts(self.universe):
            close = closes.get(f['symbol'])
            if close is None:
                continue
            close = close.dropna()
            base = pd.Timestamp(f['base_date'])
            if base not in close.index:
                continue
            position = close.index.get_loc(base)
            if position + f['days'] >= len(close):
                continue  # not over yet
            realized = float(close.iloc[position + f['days']])
            self.store.record_forecast_outcome(f['batch_id'], f['symbol'], f['horizon'],
                                               str(close.index[position + f['days']].date()), realized,
                                               **inside(realized, f))
            scored += 1
        return scored

    def backfill_forecasts(self, prepared: Optional[Dict[str, pd.DataFrame]] = None, periods: int = 60) -> int:
        """Give a new (demo) dashboard a simulated history: ranges replayed on past dates, already scored."""
        closes = self._closes(prepared)
        forecaster = self._forecaster()
        records = forecaster.backtest(closes, periods=periods)
        by_date: Dict[str, List[Dict[str, Any]]] = {}
        for r in records:
            by_date.setdefault(r['base_date'], []).append(r)
        for day, rows in sorted(by_date.items()):
            self.store.save_forecast_batch(self.universe, day, {'simulated': True}, rows, simulated=True,
                                           created_at=f'{day}T00:00:00+00:00')
        return len(records)

    def forecast_view(self) -> Optional[Dict[str, Any]]:
        """The latest ranges for every asset, with how reliable earlier ranges were."""
        batch = self.store.latest_forecast_batch(self.universe)
        if not batch:
            return None
        summary = batch['summary']
        labels = summary.get('labels', {})
        horizons = [{'key': k, 'days': d, 'label': labels.get(k, k)} for k, d in summary['horizons'].items()]

        scored = self.store.scored_forecasts(self.universe)
        live = [r for r in scored if not r['simulated']]
        simulated = [r for r in scored if r['simulated']]
        overall = {
            'live': {h['key']: reliability([r for r in live if r['horizon'] == h['key']]) for h in horizons},
            'simulated': {h['key']: reliability([r for r in simulated if r['horizon'] == h['key']])
                          for h in horizons},
        }

        latest = self.latest_analysis()
        ranking = {r['symbol']: r for r in (latest or {}).get('rankings', [])}
        live_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        simulated_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        for r in live:
            live_by_symbol.setdefault(r['symbol'], []).append(r)
        for r in simulated:
            simulated_by_symbol.setdefault(r['symbol'], []).append(r)
        assets: Dict[str, Dict[str, Any]] = {}
        for f in batch['forecasts']:
            entry = assets.get(f['symbol'])
            if entry is None:
                ranked = ranking.get(f['symbol'], {})
                own = live_by_symbol.get(f['symbol']) or simulated_by_symbol.get(f['symbol'], [])
                entry = assets[f['symbol']] = {
                    'symbol': f['symbol'],
                    'name': ranked.get('company_name') or (self.pipeline.asset_metadata(f['symbol'], None)['name']
                                                          if self.universe == 'crypto' else f['symbol']),
                    'sector': ranked.get('sector'),
                    'price': f['base_price'], 'base_date': f['base_date'],
                    'beat_probability': ranked.get('ml_probability'), 'rank': ranked.get('rank'),
                    'picked': ranked.get('picked', False),
                    'reliability_source': 'live' if any(not r['simulated'] for r in own) else 'simulated',
                    'reliability': {h['key']: reliability([r for r in own if r['horizon'] == h['key']])
                                    for h in horizons},
                }
            entry[f['horizon']] = {k: f.get(k) for k in ('q05', 'q15', 'q25', 'q50', 'q75', 'q85', 'q95', 'days', 'sigma')}
        return to_jsonable({
            'created_at': batch['created_at'], 'base_date': batch['base_date'], 'method': summary.get('method'),
            'horizons': horizons, 'evaluation': summary.get('evaluation', {}), 'reliability': overall,
            'assets': sorted(assets.values(), key=lambda a: (a['rank'] is None, a['rank'] or 0, a['symbol'])),
        })

    def asset_forecast(self, symbol: str) -> Optional[Dict[str, Any]]:
        view = self.forecast_view()
        if not view:
            return None
        asset = next((a for a in view['assets'] if a['symbol'] == symbol), None)
        if asset is None:
            return None
        return {'horizons': view['horizons'], 'base_date': view['base_date'], **asset}
