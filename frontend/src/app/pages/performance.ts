import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { ChartConfiguration } from 'chart.js';

import { ApiService } from '../core/api.service';
import { evidence, num, pct, shortDate } from '../core/format';
import { BreakdownRow, PerformanceReport } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { describeError } from '../core/universe-store';
import { ChartComponent, baseOptions, themeColors } from '../shared/chart';

@Component({
  selector: 'app-performance',
  imports: [ChartComponent, RouterLink],
  templateUrl: './performance.html',
  styleUrl: './performance.scss',
})
export class PerformancePage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  readonly universe = injectUniverse();

  /** Query parameters: ?source=live or ?backtest=<id> */
  readonly source = input<string | undefined>();
  readonly backtest = input<string | undefined>();

  readonly report = signal<PerformanceReport | null>(null);
  readonly loading = signal(true);
  readonly missing = signal(false);
  readonly error = signal<string | null>(null);
  readonly symbolFilter = signal('');

  constructor() {
    effect(() => {
      const source = this.source() === 'live' ? 'live' : 'backtest';
      const backtest = this.backtest() ?? null;
      this.loading.set(true);
      this.missing.set(false);
      this.error.set(null);
      this.api.performance(this.universe, source, backtest).subscribe({
        next: (r) => { this.report.set(r); this.loading.set(false); },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.report.set(null);
          if (err.status === 404) this.missing.set(true);
          else this.error.set(describeError(err));
        },
      });
    });
  }

  readonly selectedKey = computed(() => {
    const r = this.report();
    return r ? (r.source === 'live' ? 'live' : `backtest:${r.backtest_id}`) : '';
  });

  readonly csvUrl = computed(() => {
    const r = this.report();
    return r ? this.api.predictionsCsvUrl(this.universe, r.source, r.backtest_id) : '';
  });

  readonly verdict = computed(() => evidence(this.report()?.summary.ic?.t_stat));

  readonly filteredLog = computed(() => {
    const filter = this.symbolFilter().trim().toUpperCase();
    const rows = this.report()?.log ?? [];
    return (filter ? rows.filter((r) => r.symbol.includes(filter)) : rows).slice(0, 60);
  });

  readonly decileChart = computed<ChartConfiguration | null>(() => {
    const d = this.report()?.deciles;
    if (!d?.buckets.length) return null;
    const c = themeColors();
    const base = baseOptions((v) => num(v * 10000, 0) + ' bp') as ChartConfiguration['options'];
    return {
      type: 'bar',
      data: {
        labels: d.buckets.map((b) => b.bucket === 1 ? 'Lowest' : b.bucket === d.buckets.length ? 'Highest' : String(b.bucket)),
        datasets: [{
          label: 'Average result vs. the field',
          data: d.buckets.map((b) => b.mean_excess),
          backgroundColor: d.buckets.map((b) => (b.mean_excess >= 0 ? c.up : c.down)),
          borderRadius: 2,
        }],
      },
      options: { ...base, plugins: { ...base!.plugins, legend: { display: false } },
        scales: { ...base!.scales, x: { ...base!.scales!['x'],
          title: { display: true, text: 'Score group, from lowest to highest score', color: c.faint } } } },
    };
  });

  readonly icChart = computed<ChartConfiguration | null>(() => {
    const series = this.report()?.ic_series ?? [];
    if (series.length < 2) return null;
    const c = themeColors();
    return {
      type: 'line',
      data: {
        labels: series.map((p) => shortDate(p.date)),
        datasets: [
          { label: 'Each period', data: series.map((p) => p.ic), borderColor: c.faint, backgroundColor: c.faint,
            pointRadius: 0, borderWidth: 1 },
          { label: 'Rolling average', data: series.map((p) => p.rolling), borderColor: c.accent, backgroundColor: c.accent,
            pointRadius: 0, borderWidth: 2.5 },
          { label: 'Zero', data: series.map(() => 0), borderColor: c.ink, pointRadius: 0, borderWidth: 1, borderDash: [3, 3] },
        ],
      },
      options: baseOptions((v) => num(v, 2)) as ChartConfiguration['options'],
    };
  });

  readonly calibrationChart = computed<ChartConfiguration | null>(() => {
    const bins = this.report()?.calibration.bins ?? [];
    if (!bins.length) return null;
    const c = themeColors();
    return {
      type: 'line',
      data: {
        labels: bins.map((b) => pct(b.predicted, 0)),
        datasets: [
          { label: 'Actually beat the field', data: bins.map((b) => b.observed), borderColor: c.accent,
            backgroundColor: c.accent, pointRadius: 4, borderWidth: 2 },
          { label: 'Perfect calibration', data: bins.map((b) => b.predicted), borderColor: c.faint, borderDash: [4, 4],
            pointRadius: 0, borderWidth: 1 },
        ],
      },
      options: baseOptions((v) => pct(v, 0)) as ChartConfiguration['options'],
    };
  });

  choose(key: string): void {
    const queryParams = key === 'live' ? { source: 'live' } : { backtest: key.split(':')[1] };
    this.router.navigate([], { queryParams });
  }

  componentVerdict(t: number | null): string {
    return evidence(t).label;
  }

  breakdownTitle(kind: 'sector' | 'regime' | 'direction'): string {
    if (kind === 'sector') return this.universe === 'crypto' ? 'By coin category' : 'By sector';
    return kind === 'regime' ? 'By market mood' : 'By market direction';
  }

  breakdownRows(kind: 'sector' | 'regime' | 'direction'): BreakdownRow[] {
    return this.report()?.breakdowns[kind] ?? [];
  }

  readonly kinds = ['regime', 'direction', 'sector'] as const;
  readonly pct = pct;
  readonly num = num;
  readonly shortDate = shortDate;
  readonly evidence = evidence;
}
