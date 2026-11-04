"""
My portfolio and the weekly brief built on it.

Part of :class:`api.service.UniverseService`; methods use the shared
state set up in ``core.py`` (pipeline, store, settings).
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from api.serialization import to_jsonable
from src.personal import brief as brief_rules
from src.personal.portfolio import (DEFAULT_RULES, apply_transactions, portfolio_volatility, risk_label,
                                    risk_warnings, value_history, weekly_range)


class PortfolioMixin:
    """My portfolio and the weekly brief built on it."""

    @property
    def risk_rules(self) -> Dict[str, Any]:
        return {**DEFAULT_RULES, **(self.pipeline.universe_config.get('risk') or {})}

    def add_transaction(self, symbol: str, side: str, trade_date: str, quantity: float, price: float,
                        fees: float = 0.0, note: Optional[str] = None) -> Dict[str, Any]:
        """
        Record a trade after checking it against the history (a sale cannot
        exceed what was held on its date).

        Raises:
            TransactionError: the trade would make a holding negative
        """
        candidate = {'symbol': symbol, 'side': side, 'trade_date': trade_date, 'quantity': quantity,
                     'price': price, 'fees': fees, 'created_at': '9999', 'id': 'new'}
        apply_transactions([*self.store.list_transactions(self.universe), candidate])
        return self.store.add_transaction(self.universe, symbol, side, trade_date, quantity, price, fees, note)

    def delete_transaction(self, transaction_id: str) -> bool:
        """Remove a trade, unless a later sale depends on it."""
        remaining = [t for t in self.store.list_transactions(self.universe) if t['id'] != transaction_id]
        apply_transactions(remaining)
        return self.store.delete_transaction(self.universe, transaction_id)

    def _closes_since(self, symbols: List[str], start: str) -> Dict[str, pd.Series]:
        """Daily closes for these symbols from ``start``: the latest analysis's data when it covers them."""
        begin = pd.Timestamp(start)
        closes: Dict[str, pd.Series] = {}
        for s in symbols:
            data = self.prepared.get(s)
            if data is not None and 'Close' in data and len(data) and data.index[0] <= begin:
                closes[s] = data['Close']
        missing = [s for s in symbols if s not in closes]
        if missing:
            days = (pd.Timestamp.now().normalize() - begin).days
            period = next(p for limit, p in ((150, '6mo'), (330, '1y'), (700, '2y'), (10 ** 9, '5y')) if days <= limit)
            raw = self.pipeline.data_collector.fetch_multiple_stocks(missing, period=period)
            closes.update({s: d['Close'] for s, d in raw.items() if d is not None and not d.empty})
        return closes

    def _benchmark(self, start: str) -> Optional[pd.Series]:
        """The comparison for your portfolio: Bitcoin for crypto, the average asset of the list for stocks."""
        if self.universe == 'crypto':
            btc = self._closes_since(['BTC-USD'], start).get('BTC-USD')
            return btc / btc.dropna().iloc[0] if btc is not None and len(btc.dropna()) else None
        closes = self._closes(self.prepared or None)
        if not closes:
            return None
        returns = pd.DataFrame({s: c.pct_change() for s, c in closes.items()})
        average = returns[returns.index >= pd.Timestamp(start) - pd.Timedelta(days=7)].mean(axis=1).fillna(0.0)
        return (1 + average).cumprod()

    def portfolio_view(self) -> Dict[str, Any]:
        """Your holdings, gains, history against the benchmark, risk and warnings."""
        rules = self.risk_rules
        txs = self.store.list_transactions(self.universe)
        benchmark_label = 'Bitcoin' if self.universe == 'crypto' else f'the average stock of the {len(self.pipeline.symbols)} in the list'
        base = {'universe': self.universe, 'rules': rules, 'benchmark_label': benchmark_label,
                'transactions': to_jsonable(list(reversed(txs))), 'symbols': self.pipeline.symbols}
        if not txs:
            return {**base, 'empty': True, 'positions': [], 'warnings': [], 'history': [], 'sectors': [], 'summary': None}

        holdings = apply_transactions(txs)
        start = min(t['trade_date'] for t in txs)
        closes = self._closes_since(sorted(holdings), start)
        latest = self.latest_analysis()
        ranked = {r['symbol']: r for r in (latest or {}).get('rankings', [])}
        universe_size = len(ranked) or None
        batch = self.store.latest_forecast_batch(self.universe)
        week_key = 'week'
        ranges = {f['symbol']: f for f in (batch or {}).get('forecasts', []) if f['horizon'] == week_key}

        positions = []
        for symbol, h in sorted(holdings.items()):
            series = closes.get(symbol)
            price = float(series.dropna().iloc[-1]) if series is not None and len(series.dropna()) else None
            value = h.quantity * price if price is not None else None
            r = ranked.get(symbol, {})
            rng = ranges.get(symbol)
            positions.append({
                'symbol': symbol,
                'name': r.get('company_name') or (self.pipeline.asset_metadata(symbol, None)['name']
                                                  if self.universe == 'crypto' else symbol),
                'sector': r.get('sector') or (self.pipeline.asset_metadata(symbol, None)['sector']
                                              if self.universe == 'crypto' else None),
                'quantity': h.quantity, 'average_cost': h.average_cost, 'price': price, 'value': value,
                'cost_basis': h.cost_basis,
                'unrealized': (value - h.cost_basis) if value is not None and h.quantity > 0 else 0.0,
                'unrealized_pct': (value / h.cost_basis - 1) if value is not None and h.cost_basis > 0 else None,
                'realized': h.realized, 'fees': h.fees, 'first_date': h.first_date, 'trades': h.trades,
                'rank': r.get('rank'), 'universe_size': universe_size, 'score': r.get('composite_score'),
                'beat_probability': r.get('ml_probability'), 'picked': bool(r.get('picked')),
                'vol_forecast': r.get('vol_forecast'), 'vol_up_probability': r.get('vol_up_probability'),
                'week_range': {'low': rng['q05'], 'high': rng['q95'], 'days': rng['days']} if rng else None,
            })
        held = [p for p in positions if p['quantity'] > 0]
        total = sum(p['value'] or 0.0 for p in held)
        for p in positions:
            p['weight'] = (p['value'] or 0.0) / total if total > 0 and p['quantity'] > 0 else 0.0

        weights = {p['symbol']: p['weight'] for p in held}
        volatility = portfolio_volatility(weights, closes, periods_per_year=self.pipeline.periods_per_year)
        history = value_history(txs, closes, self._benchmark(start))
        invested = float(history['invested'].iloc[-1]) if len(history) else None
        bought = sum(t['quantity'] * t['price'] + (t.get('fees') or 0.0) for t in txs if t['side'] == 'buy')
        realized = sum(p['realized'] for p in positions)
        unrealized = sum(p['unrealized'] for p in held)
        benchmark_value = float(history['benchmark_value'].iloc[-1]) \
            if 'benchmark_value' in history and len(history) and pd.notna(history['benchmark_value'].iloc[-1]) else None
        sectors: Dict[str, float] = {}
        for p in held:
            sectors[p['sector'] or 'Unknown'] = sectors.get(p['sector'] or 'Unknown', 0.0) + p['weight']
        week_days = 7 if self.universe == 'crypto' else 5
        summary = {
            'value': total, 'invested': invested, 'bought': bought,
            'gain': unrealized + realized, 'unrealized': unrealized, 'realized': realized,
            'gain_pct': (unrealized + realized) / bought if bought > 0 else None,
            'benchmark_value': benchmark_value,
            'vs_benchmark': total - benchmark_value if benchmark_value is not None else None,
            'volatility': volatility, 'risk_label': risk_label(volatility),
            'next_week': weekly_range(total, volatility, week_days, self.pipeline.periods_per_year),
            'positions': len(held), 'as_of': max((str(c.dropna().index[-1].date()) for c in closes.values()
                                                  if len(c.dropna())), default=None),
            'since': start,
        }
        warnings = risk_warnings(held, volatility, rules, sectors=self.universe == 'stocks')
        step = max(1, len(history) // 400)  # keep the chart light
        points = history.iloc[::step]
        if len(history) and points.index[-1] != history.index[-1]:
            points = pd.concat([points, history.iloc[[-1]]])
        return to_jsonable({
            **base, 'empty': False, 'summary': summary, 'positions': positions, 'warnings': warnings,
            'sectors': [{'sector': k, 'weight': v} for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])],
            'history': [{'date': str(d.date()), 'value': float(r['value']), 'invested': float(r['invested']),
                         'benchmark': float(r['benchmark_value']) if 'benchmark_value' in r and pd.notna(r['benchmark_value']) else None}
                        for d, r in points.iterrows()],
        })

    def brief(self) -> Dict[str, Any]:
        """The weekly brief: the market, your portfolio, the model, ideas, alerts and what to do."""
        crypto = self.universe == 'crypto'
        days = 7 if crypto else 5
        period = 'week'
        noun = 'coins' if crypto else 'stocks'
        closes = self._closes(self.prepared or None)
        analysis = self.latest_analysis()
        names = {r['symbol']: r['symbol'] for r in (analysis or {}).get('rankings', [])}
        as_of = max((str(c.dropna().index[-1].date()) for c in closes.values() if len(c.dropna())), default=None)

        market = brief_rules.market_section(closes, days, names, noun, period)
        portfolio = self.portfolio_view()
        mine = brief_rules.portfolio_section(portfolio, days if crypto else 7, period)
        quality = (analysis or {}).get('summary', {}).get('model_quality', {}) if analysis else {}
        model = brief_rules.model_section(self.track_record(), quality, self.pipeline.horizon)
        batch = self.store.latest_forecast_batch(self.universe)
        ranges = {f['symbol']: f for f in (batch or {}).get('forecasts', []) if f['horizon'] == 'week'}
        ideas = brief_rules.ideas_section(analysis, ranges, model['facts']['proven'], long_term=self.long_term_view())
        since = str((pd.Timestamp(as_of) - pd.Timedelta(days=7)).date()) if as_of else None
        alerts = [a for a in self.notifier.store.list(self.universe, limit=200)
                  if since is None or a['event_date'] >= since]
        held = [p['symbol'] for p in portfolio.get('positions', []) if p['quantity'] > 0]
        alert_section = brief_rules.alerts_section(alerts, held)
        age = None
        if analysis:
            age = (pd.Timestamp.now().normalize() - pd.Timestamp(analysis['run']['data_date'])).days
        todo = brief_rules.actions(mine and portfolio, model, age, alert_section)
        sections = [s for s in (market, mine, model, ideas, alert_section) if s]
        result = {
            'universe': self.universe, 'as_of': as_of,
            'title': f"{self.pipeline.label}: your week in two minutes",
            'subtitle': f"Prices up to {brief_rules.nice_date(as_of)}." + (' Simulated demo prices.' if self.settings.demo_mode else ''),
            'sections': sections, 'actions': todo,
        }
        return to_jsonable(result)

    def brief_markdown(self) -> str:
        return brief_rules.to_markdown(self.brief())
