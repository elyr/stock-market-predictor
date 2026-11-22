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
  templateUrl: './asset.html',
  styleUrl: './asset.scss',
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
    const end = Math.log((week[key] as number) / week.q50);
    for (let k = 1; k <= week.days; k++) values.push(week.q50 * Math.exp(end * Math.sqrt(k / week.days)));
    return values;
  };
  return { labels, series };
}
