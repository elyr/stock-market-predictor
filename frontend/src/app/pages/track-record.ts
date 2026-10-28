import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ChartConfiguration } from 'chart.js';

import { ApiService } from '../core/api.service';
import { evidence, num, pct, shortDate } from '../core/format';
import { TrackRecord, TrackSummary } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { UniverseStores, describeError } from '../core/universe-store';
import { ChartComponent, baseOptions, themeColors } from '../shared/chart';

@Component({
  selector: 'app-track-record',
  imports: [ChartComponent, RouterLink],
  template: `
    <section class="section intro">
      <h2>Every prediction, scored after the fact</h2>
      <p class="muted">
        Each analysis is saved with its prices before anyone knows the outcome. Once its
        {{ store.info()?.horizon_days ?? 5 }}-day horizon has passed, the picks are scored against the
        average {{ universe === 'crypto' ? 'coin' : 'stock' }}. Nothing here can be adjusted afterwards.
      </p>
      <button class="btn" type="button" (click)="evaluate()" [disabled]="busy()">
        @if (busy()) { <span class="spinner" aria-hidden="true"></span> Checking } @else { Check for new results }
      </button>
      @if (message(); as m) { <p class="small faint" aria-live="polite">{{ m }}</p> }
      @if (error(); as e) { <p class="notice error" role="alert">{{ e }}</p> }
    </section>

    @if (record(); as r) {
      @for (block of blocks(r); track block.key) {
        <section class="section">
          <div class="section-head">
            <div>
              <h2>{{ block.title }}</h2>
              <p class="muted">{{ block.note }}</p>
            </div>
          </div>
          @if (block.data.evaluated) {
            <div class="facts">
              <div><div class="fact-value" [class.up]="(block.data.avg_excess_return ?? 0) > 0" [class.down]="(block.data.avg_excess_return ?? 0) < 0">
                {{ pct(block.data.avg_excess_return, 2, true) }}</div><div class="fact-label">Average edge over the field per period</div></div>
              <div><div class="fact-value">{{ pct(block.data.hit_rate, 0) }}</div><div class="fact-label">Periods the picks beat the field</div></div>
              <div><div class="fact-value">{{ num(block.data.avg_rank_ic, 3, true) }}</div><div class="fact-label">Average rank IC</div></div>
              <div><div class="fact-value">{{ block.data.evaluated }}</div><div class="fact-label">Periods scored, {{ block.data.pending }} still open</div></div>
            </div>
            <p class="verdict"><strong>{{ verdict(block.data).label }}</strong> (t = {{ num(block.data.excess_t_stat, 1) }}).</p>
            @if (chart(block.data); as c) {
              <app-chart [config]="c" [height]="260" [label]="block.title + ' cumulative return'" />
            }
          } @else {
            <p class="muted">
              @if (block.data.pending) {
                {{ block.data.pending }} {{ block.data.pending === 1 ? 'analysis is' : 'analyses are' }} waiting for
                {{ store.info()?.horizon_days ?? 5 }} days of prices before they can be scored.
              } @else {
                Nothing yet. <a routerLink="..">Run an analysis</a> to start the record.
              }
            </p>
          }
        </section>
      }

      @if (liveRuns().length) {
        <section class="section">
          <h3>Live analyses</h3>
          <div class="table-wrap">
            <table class="data">
              <thead><tr><th scope="col">Prices as of</th><th scope="col">Scored on</th><th scope="col" class="num">Picks</th>
                <th scope="col" class="num">Field</th><th scope="col" class="num">Edge</th><th scope="col" class="num">Rank IC</th></tr></thead>
              <tbody>
                @for (run of liveRuns(); track run.id) {
                  <tr>
                    <td>{{ shortDate(run.data_date) }}</td>
                    <td>{{ run.evaluated_at ? shortDate(run.exit_date) : 'Open' }}</td>
                    <td class="num">{{ pct(run.portfolio_return, 2, true) }}</td>
                    <td class="num">{{ pct(run.universe_return, 2, true) }}</td>
                    <td class="num" [class.up]="(run.excess_return ?? 0) > 0" [class.down]="(run.excess_return ?? 0) < 0">{{ pct(run.excess_return, 2, true) }}</td>
                    <td class="num">{{ num(run.rank_ic, 3, true) }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      }
    }
  `,
  styles: `
    .intro { padding-top: 2rem; }
    .intro > p { margin: 0.5rem 0 1.25rem; }
    .verdict { margin: 1.25rem 0; }
  `,
})
export class TrackRecordPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly store = inject(UniverseStores).get(this.universe);
  readonly record = signal<TrackRecord | null>(null);
  readonly busy = signal(false);
  readonly message = signal('');
  readonly error = signal<string | null>(null);

  readonly liveRuns = computed(() => (this.record()?.runs ?? []).filter((r) => !r.simulated));

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.trackRecord(this.universe).subscribe({
      next: (r) => this.record.set(r),
      error: (err) => this.error.set(describeError(err)),
    });
  }

  evaluate(): void {
    this.busy.set(true);
    this.api.evaluateOutcomes(this.universe).subscribe({
      next: (job) => this.api.watchJob(job.id).subscribe({
        next: (update) => {
          if (update.status === 'succeeded') {
            const n = (update.result as { evaluated_runs?: number } | null)?.evaluated_runs ?? 0;
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
      note: 'Analyses run in this app, scored on real subsequent prices.' }];
    if (r.simulated.evaluated) {
      blocks.push({ key: 'simulated', title: 'Simulated history', data: r.simulated,
        note: 'Demo only: periods from a walk-forward backtest, shown so the page is not empty. Not real predictions.' });
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
