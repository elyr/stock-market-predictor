import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ChartConfiguration } from 'chart.js';

import { ApiService } from '../core/api.service';
import { evidence, num, pct, shortDate } from '../core/format';
import { ForecastView, TrackRecord, TrackSummary } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { UniverseStores, describeError } from '../core/universe-store';
import { ChartComponent, baseOptions, themeColors } from '../shared/chart';
import { HintComponent } from '../shared/hint';

@Component({
  selector: 'app-track-record',
  imports: [ChartComponent, RouterLink, HintComponent],
  templateUrl: './track-record.html',
  styleUrl: './track-record.scss',
})
export class TrackRecordPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly store = inject(UniverseStores).get(this.universe);
  readonly record = signal<TrackRecord | null>(null);
  readonly forecast = signal<ForecastView | null>(null);
  readonly busy = signal(false);
  readonly message = signal('');
  readonly error = signal<string | null>(null);

  readonly liveAnalyses = computed(() => (this.record()?.analyses ?? []).filter((r) => !r.simulated));

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.trackRecord(this.universe).subscribe({
      next: (r) => this.record.set(r),
      error: (err) => this.error.set(describeError(err)),
    });
    // No forecast yet is normal: the section is simply not shown
    this.api.forecast(this.universe).subscribe({ next: (f) => this.forecast.set(f), error: () => this.forecast.set(null) });
  }

  evaluate(): void {
    this.busy.set(true);
    this.api.evaluateOutcomes(this.universe).subscribe({
      next: (job) => this.api.watchJob(job.id).subscribe({
        next: (update) => {
          if (update.status === 'succeeded') {
            const n = (update.result as { evaluated_analyses?: number } | null)?.evaluated_analyses ?? 0;
            this.message.set(n ? `${n} more ${n === 1 ? 'analysis' : 'analyses'} scored.` : 'No analyses have matured since the last check.');
            this.busy.set(false);
            this.load();
          } else if (update.status === 'failed') {
            this.busy.set(false);
            this.error.set(update.error ?? 'Checking results failed.');
          }
        },
      }),
      error: (err) => { this.busy.set(false); this.error.set(describeError(err)); },
    });
  }

  blocks(r: TrackRecord) {
    const blocks = [{ key: 'live', title: 'Live record', data: r.live,
      note: 'Analyses made in this app, scored on real subsequent prices.' }];
    if (r.simulated.evaluated) {
      blocks.push({ key: 'simulated', title: 'Simulated history', data: r.simulated,
        note: 'Demo only: periods from a walk-forward backtest, shown so the page is not empty. Not real scores.' });
    }
    return blocks;
  }

  verdict(data: TrackSummary) {
    return evidence(data.excess_t_stat);
  }

  chart(data: TrackSummary): ChartConfiguration | null {
    if (!data.curve?.length) return null;
    const c = themeColors();
    return {
      type: 'line',
      data: {
        labels: data.curve.map((p) => shortDate(p.date)),
        datasets: [
          { label: 'Picks', data: data.curve.map((p) => p.portfolio), borderColor: c.accent, backgroundColor: c.accent, pointRadius: 0, borderWidth: 2.5 },
          { label: 'Whole field', data: data.curve.map((p) => p.universe), borderColor: c.ink, backgroundColor: c.ink, pointRadius: 0, borderWidth: 1.5 },
        ],
      },
      options: baseOptions((v) => pct(v, 0)) as ChartConfiguration['options'],
    };
  }

  readonly pct = pct;
  readonly num = num;
  readonly shortDate = shortDate;
}
