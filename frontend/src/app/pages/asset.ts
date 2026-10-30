import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ChartConfiguration } from 'chart.js';

import { ApiService } from '../core/api.service';
import { num, pct, price, shortDate } from '../core/format';
import { AssetDetail, PriceRange } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { describeError } from '../core/universe-store';
import { ChartComponent, baseOptions, themeColors } from '../shared/chart';
import { ScoreBarComponent } from '../shared/score-bar';
import { HintComponent } from '../shared/hint';

@Component({
  selector: 'app-asset',
  imports: [RouterLink, ChartComponent, ScoreBarComponent, HintComponent],
  template: `
    <p class="back"><a routerLink="../..">Back to the outlook</a></p>
    @if (error(); as e) { <p class="notice error" role="alert">{{ e }}</p> }
    @if (!detail() && !error()) { <p class="muted"><span class="spinner" aria-hidden="true"></span> Loading {{ symbol() }}</p> }

    @if (detail(); as d) {
      @let last = d.history[d.history.length - 1];
      <header class="asset-head">
        <div>
          <h2>{{ d.symbol }} <span class="name">{{ d.name }}</span></h2>
          <p class="muted">{{ d.latest?.sector }}</p>
        </div>
        <div class="price-block">
          <span class="price">{{ price(last.close) }}</span>
          @if (d.latest; as l) {
            <span [class.up]="l.daily_change_pct > 0" [class.down]="l.daily_change_pct < 0">{{ pct(l.daily_change_pct / 100, 2, true) }} today</span>
          }
        </div>
      </header>

      @if (d.latest; as l) {
        <section class="section standing">
          <div class="facts">
            <div><div class="fact-value">{{ l.rank }}</div><div class="fact-label">Rank</div>
              <div class="fact-note">{{ l.picked ? 'In the suggested portfolio' : 'In the latest analysis' }}</div></div>
            <div><div class="fact-value">{{ l.composite_score.toFixed(0) }}</div><div class="fact-label">Score <app-hint term="score" /></div>
              <div class="fact-note">Out of 100</div></div>
            <div><div class="fact-value">{{ pct(l.ml_probability, 1) }}</div><div class="fact-label">Chance to beat the field <app-hint term="beat" /></div>
              <div class="fact-note">Over {{ l.horizon_days }} days</div></div>
            <div><div class="fact-value">{{ pct(l.vol_forecast, 0) }}</div><div class="fact-label">Volatility forecast <app-hint term="volForecast" /></div>
              <div class="fact-note">Now {{ pct(l.volatility, 0) }}</div></div>
          </div>
        </section>
      }

      <section class="section">
        <h3>Price, 50-day average and Bollinger band{{ d.forecast?.week ? ', and where it may go' : '' }}</h3>
        @if (priceChart(); as c) { <app-chart [config]="c" [height]="300" [label]="d.symbol + ' price chart'" /> }
        @if (d.forecast; as f) {
          <div class="forecast">
            @for (h of f.horizons; track h.key) {
              @if (f[h.key]; as r) {
                <div>
                  <div class="fact-label">{{ h.label }} <app-hint term="range90" /></div>
                  <div class="forecast-range">{{ price(r.q05) }} – {{ price(r.q95) }}</div>
                  <div class="small muted">9 times in 10; half the time {{ price(r.q25) }} – {{ price(r.q75) }}</div>
                </div>
              }
            }
            <p class="small faint">
              Ranges from {{ shortDate(f.base_date) }}, centred on that day's price; the shaded fan on the chart shows
              the next-week range widening day by day.
              @if (f.reliability['week']; as w) {
                @if (w.scored > 0) {
                  This asset's past 90% ranges held {{ pct(w.coverage_90, 0) }} of {{ w.scored }}
                  times{{ f.reliability_source === 'simulated' ? ' (replayed on past dates)' : '' }}.
                }
              }
              <a routerLink="../../forecast">All assets</a>
            </p>
          </div>
        }
      </section>

      <section class="section split">
        <div>
          <h3>RSI <app-hint label="RSI" text="Relative strength index: compares recent gains with recent losses on a 0–100 scale. A popular chart reading, shown for context; the model uses its own inputs." /></h3>
          <p class="small muted">Below 30 is often read as oversold, above 70 as overbought.</p>
          @if (rsiChart(); as c) { <app-chart [config]="c" [height]="180" label="RSI" /> }
        </div>
        <div>
          <h3>Why it ranks where it does <app-hint term="scoreParts" /></h3>
          @if (d.latest; as l) {
            <dl class="scores">
              <dt>Model</dt><dd><app-score-bar [value]="l.ml_score" label="Model" /></dd>
              <dt>Technical</dt><dd><app-score-bar [value]="l.technical_score" label="Technical" /></dd>
              <dt>Momentum</dt><dd><app-score-bar [value]="l.momentum_score" label="Momentum" /></dd>
              <dt>Volume</dt><dd><app-score-bar [value]="l.volume_score" label="Volume" /></dd>
            </dl>
            @if (l.explanation.length) {
              <ul class="reasons">
                @for (c of l.explanation; track c.feature) {
                  <li><span [class.up]="c.contribution > 0" [class.down]="c.contribution < 0">{{ c.contribution > 0 ? 'For' : 'Against' }}</span>: {{ c.label }}</li>
                }
              </ul>
            }
          }
          @if (d.signals.length) {
            <h3 class="signals-title">Signals</h3>
            <ul class="reasons">@for (s of d.signals; track s) { <li>{{ s }}</li> }</ul>
          }
        </div>
      </section>
    }
  `,
  styles: `
    .back { margin: 1.5rem 0 0; font-size: var(--step--1); }
    .back a { color: var(--accent); }
    .asset-head { display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 1rem; padding: 1rem 0 1.5rem; }
    .name { font-weight: 500; color: var(--ink-soft); font-size: var(--step-1); margin-left: 0.4rem; }
    .price-block { display: grid; justify-items: end; }
    .price { font-size: var(--step-2); font-weight: 700; }
    .split { display: grid; grid-template-columns: 1fr 1fr; gap: 3rem; }
    .split h3, .section > h3 { margin-bottom: 0.5rem; }
    .scores { display: grid; grid-template-columns: 6rem 1fr; gap: 0.3rem 0.75rem; margin: 0.75rem 0 1rem; align-items: center; }
    .scores dt { color: var(--ink-soft); font-size: var(--step--1); }
    .scores dd { margin: 0; }
    .reasons { margin: 0.25rem 0 0; padding-left: 1.1rem; font-size: var(--step--1); }
    .signals-title { margin-top: 1rem; }
    .forecast { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: 0.5rem 2rem; margin-top: 1rem; }
    .forecast p { grid-column: 1 / -1; margin: 0; }
    .forecast-range { font-size: var(--step-1); font-weight: 700; font-variant-numeric: tabular-nums; }
    @media (max-width: 900px) { .split { grid-template-columns: 1fr; } }
  `,
})
export class AssetPage {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly symbol = input.required<string>();
  readonly detail = signal<AssetDetail | null>(null);
  readonly error = signal<string | null>(null);

  constructor() {
    effect(() => {
      const symbol = this.symbol();
      this.detail.set(null);
      this.error.set(null);
      this.api.asset(this.universe, symbol).subscribe({
        next: (d) => this.detail.set(d),
        error: (err) => this.error.set(describeError(err)),
      });
    });
  }

  readonly priceChart = computed<ChartConfiguration | null>(() => {
    const d = this.detail();
    if (!d) return null;
    const c = themeColors();
    const fan = forecastFan(d);
    // With a forecast, fewer past days so the fan ahead is readable
    const h = fan.labels.length ? d.history.slice(-120) : d.history;
    const pad = (values: (number | null)[]) => [...values, ...fan.labels.map(() => null)];
    return {
      type: 'line',
      data: {
        labels: [...h.map((p) => shortDate(p.date)), ...fan.labels],
        datasets: [
          { label: 'Upper band', data: pad(h.map((p) => p.bb_upper)), borderColor: 'transparent', pointRadius: 0, fill: false, order: 4 },
          { label: 'Lower band', data: pad(h.map((p) => p.bb_lower)), borderColor: 'transparent', backgroundColor: c.accentWash,
            pointRadius: 0, fill: '-1', order: 4 },
          { label: 'Close', data: pad(h.map((p) => p.close)), borderColor: c.accent, backgroundColor: c.accent, pointRadius: 0, borderWidth: 2, order: 0 },
          { label: '50-day average', data: pad(h.map((p) => p.sma_50)), borderColor: c.faint, backgroundColor: c.faint,
            pointRadius: 0, borderWidth: 1.25, borderDash: [4, 3], order: 1 },
          ...(fan.labels.length ? [
            { label: 'Forecast band 95', data: fan.series(h.length, 'q95'), borderColor: c.accent, borderWidth: 1,
              borderDash: [2, 3], pointRadius: 0, fill: false, order: 3 },
            { label: 'Forecast band 5', data: fan.series(h.length, 'q05'), borderColor: c.accent, borderWidth: 1,
              borderDash: [2, 3], backgroundColor: c.accentWash, pointRadius: 0, fill: '-1', order: 3 },
            { label: 'Forecast band 75', data: fan.series(h.length, 'q75'), borderColor: 'transparent', pointRadius: 0, fill: false, order: 2 },
            { label: 'Forecast band 25', data: fan.series(h.length, 'q25'), borderColor: 'transparent', backgroundColor: c.accentWash,
              pointRadius: 0, fill: '-1', order: 2 },
          ] : []),
        ],
      },
      options: { ...baseOptions((v) => price(v)), plugins: { ...baseOptions((v) => price(v)).plugins,
        legend: { labels: { color: c.soft, boxWidth: 12, boxHeight: 2,
          filter: (item: { text: string }) => !item.text.includes('band') } } } } as ChartConfiguration['options'],
    };
  });

  readonly rsiChart = computed<ChartConfiguration | null>(() => {
    const d = this.detail();
    if (!d) return null;
    const c = themeColors();
    const h = d.history;
    const base = baseOptions((v) => num(v, 0)) as ChartConfiguration['options'];
    return {
      type: 'line',
      data: {
        labels: h.map((p) => shortDate(p.date)),
        datasets: [
          { label: 'RSI', data: h.map((p) => p.rsi), borderColor: c.ink, backgroundColor: c.ink, pointRadius: 0, borderWidth: 1.5 },
          { label: '70', data: h.map(() => 70), borderColor: c.down, borderDash: [3, 3], pointRadius: 0, borderWidth: 1 },
          { label: '30', data: h.map(() => 30), borderColor: c.up, borderDash: [3, 3], pointRadius: 0, borderWidth: 1 },
        ],
      },
      options: { ...base, plugins: { ...base!.plugins, legend: { display: false } },
        scales: { ...base!.scales, y: { ...base!.scales!['y'], min: 0, max: 100 } } },
    };
  });

  readonly pct = pct;
  readonly num = num;
  readonly price = price;
  readonly shortDate = shortDate;
}

/**
 * The next-week range as a fan after the last price: it widens with the square
 * root of time, as the size of moves does, from today's price to the range.
 */
function forecastFan(d: AssetDetail) {
  const week: PriceRange | undefined = d.forecast?.week;
  const last = d.history[d.history.length - 1];
  if (!week || !last) {
    return { labels: [] as string[], series: (_: number, __: keyof PriceRange) => [] as (number | null)[] };
  }
  const crypto = d.universe === 'crypto';
  const labels: string[] = [];
  const date = new Date(last.date + 'T12:00:00');
  while (labels.length < week.days) {
    date.setDate(date.getDate() + 1);
    if (!crypto && (date.getDay() === 0 || date.getDay() === 6)) continue; // stocks: trading days
    labels.push(shortDate(date.toISOString().slice(0, 10)));
  }
  const series = (historyLength: number, key: keyof PriceRange) => {
    const values: (number | null)[] = Array(historyLength - 1).fill(null);
    values.push(last.close);
    const end = Math.log(week[key] / week.q50);
    for (let k = 1; k <= week.days; k++) values.push(week.q50 * Math.exp(end * Math.sqrt(k / week.days)));
    return values;
  };
  return { labels, series };
}
