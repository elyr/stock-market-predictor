import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ChartConfiguration } from 'chart.js';

import { ApiService } from '../core/api.service';
import { bps, evidence, num, pct, shortDate } from '../core/format';
import { BacktestListItem, BacktestRecord } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { UniverseStores, describeError } from '../core/universe-store';
import { ChartComponent, baseOptions, themeColors } from '../shared/chart';

const VISIBLE = ['composite_net', 'universe'];

@Component({
  selector: 'app-backtest',
  imports: [FormsModule, ChartComponent],
  templateUrl: './backtest.html',
  styleUrl: './backtest.scss',
})
export class BacktestPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly store = inject(UniverseStores).get(this.universe);

  readonly history = signal<BacktestListItem[]>([]);
  readonly selected = signal<BacktestRecord | null>(null);
  readonly running = signal(false);
  readonly status = signal('');
  readonly error = signal<string | null>(null);

  form = { top_n: 10, test_days: 120, cost_bps: this.universe === 'crypto' ? 15 : 5, use_ml: true };

  readonly result = computed(() => this.selected()?.result ?? null);
  readonly composite = computed(() => this.result()?.metrics.find((m) => m.strategy === 'Composite after costs') ?? null);
  readonly benchmark = computed(() => this.result()?.metrics.find((m) => m.strategy === 'Equal-weight universe') ?? null);
  readonly verdict = computed(() => evidence(this.composite()?.excess_t_stat));

  readonly equityChart = computed<ChartConfiguration | null>(() => {
    const r = this.result();
    if (!r) return null;
    const c = themeColors();
    const palette: Record<string, string> = {
      composite_net: c.accent, composite: c.accent, universe: c.ink, ml_prediction: c.up,
      technical_score: '#c28a2b', momentum_score: '#8a6f9e', volume_score: c.faint,
    };
    return {
      type: 'line',
      data: {
        labels: r.dates.map((d) => shortDate(d)),
        datasets: Object.entries(r.curves).map(([key, curve]) => ({
          label: curve.label,
          data: curve.values,
          borderColor: palette[key] ?? c.soft,
          backgroundColor: palette[key] ?? c.soft,
          borderWidth: key === 'composite_net' || key === 'universe' ? 2.5 : 1.5,
          borderDash: key === 'composite' ? [5, 4] : undefined,
          pointRadius: 0,
          hidden: !VISIBLE.includes(key),
        })),
      },
      options: baseOptions((v) => pct(v, 0)) as ChartConfiguration['options'],
    };
  });

  ngOnInit(): void {
    this.loadHistory(true);
    this.api.jobs(this.universe).subscribe((jobs) => {
      const active = jobs.find((j) => j.kind === 'backtest' && (j.status === 'running' || j.status === 'queued'));
      if (active) this.watch(active.id);
    });
  }

  loadHistory(selectLatest = false): void {
    this.api.backtests(this.universe).subscribe({
      next: (list) => {
        this.history.set(list);
        if (selectLatest && list.length) this.open(list[0].id);
      },
      error: (err) => this.error.set(describeError(err)),
    });
  }

  open(id: string): void {
    this.api.backtest(this.universe, id).subscribe({
      next: (record) => this.selected.set(record),
      error: (err) => this.error.set(describeError(err)),
    });
  }

  run(): void {
    this.error.set(null);
    this.api.startBacktest(this.universe, { ...this.form }).subscribe({
      next: (job) => this.watch(job.id),
      error: (err) => this.error.set(describeError(err)),
    });
  }

  private watch(jobId: string): void {
    this.running.set(true);
    this.api.watchJob(jobId).subscribe({
      next: (job) => {
        this.status.set(job.message);
        if (job.status === 'succeeded') {
          this.running.set(false);
          const id = (job.result as { backtest_id?: string } | null)?.backtest_id;
          this.loadHistory();
          if (id) this.open(id);
        } else if (job.status === 'failed') {
          this.running.set(false);
          this.error.set(job.error ?? 'The backtest failed.');
        }
      },
      error: (err) => { this.running.set(false); this.error.set(describeError(err)); },
    });
  }

  readonly pct = pct;
  readonly num = num;
  readonly bps = bps;
  readonly shortDate = shortDate;
}
