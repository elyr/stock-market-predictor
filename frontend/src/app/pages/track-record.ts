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
                {{ pct(block.data.avg_excess_return, 2, true) }}</div><div class="fact-label">Edge over the field <app-hint term="excess" /></div><div class="fact-note">Average per period</div></div>
              <div><div class="fact-value">{{ pct(block.data.hit_rate, 0) }}</div><div class="fact-label">Periods the picks beat the field <app-hint term="hitRate" /></div></div>
              <div><div class="fact-value">{{ num(block.data.avg_rank_ic, 3, true) }}</div><div class="fact-label">Average rank IC <app-hint term="ic" /></div></div>
              <div><div class="fact-value">{{ block.data.evaluated }}</div><div class="fact-label">Periods scored</div><div class="fact-note">{{ block.data.pending }} still open</div></div>
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
                <th scope="col" class="num">Field <app-hint label="Field" text="Average return of every asset in the universe over the same period." /></th>
                <th scope="col" class="num">Edge <app-hint term="excess" /></th><th scope="col" class="num">Rank IC <app-hint term="ic" /></th></tr></thead>
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

    @if (forecast(); as f) {
      <section class="section">
        <div class="section-head">
          <div>
            <h2>Price ranges, checked after the fact</h2>
            <p class="muted">How often the price ended up inside the ranges on the <a routerLink="../forecast">Forecast</a> page.
              A 90% range should hold about 9 times in 10, a 50% range about half the time.</p>
          </div>
        </div>
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th scope="col">Horizon</th><th scope="col">Forecasts</th><th scope="col" class="num">Scored</th>
              <th scope="col" class="num">Inside the 50% range <app-hint term="range50" /></th>
              <th scope="col" class="num">Inside the 90% range <app-hint term="range90" /></th></tr></thead>
            <tbody>
              @for (h of f.horizons; track h.key) {
                @for (row of [{ name: 'Live', data: f.reliability.live[h.key] }, { name: 'Replayed on past dates', data: f.reliability.simulated[h.key] }]; track row.name) {
                  @if (row.data?.scored || row.name === 'Live') {
                    <tr>
                      <td>{{ h.label }}</td>
                      <td>{{ row.name }}</td>
                      <td class="num">{{ row.data?.scored ?? 0 }}</td>
                      <td class="num">{{ pct(row.data?.coverage_50, 0) }}</td>
                      <td class="num" [class.down]="(row.data?.coverage_90 ?? 1) < 0.8">{{ pct(row.data?.coverage_90, 0) }}</td>
                    </tr>
                  }
                }
              }
            </tbody>
          </table>
        </div>
        @if (!f.reliability.live['day']?.scored) {
          <p class="small faint note">Live ranges are scored once their window has passed: after the next
            {{ universe === 'crypto' ? 'day' : 'session' }} for the short range, after a week for the long one.</p>
        }
      </section>
    }
  `,
  styles: `
    .intro { padding-top: 2rem; }
    .intro > p { margin: 0.5rem 0 1.25rem; }
    .verdict { margin: 1.25rem 0; }
    .note { margin-top: 0.75rem; }
  `,
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

  readonly liveRuns = computed(() => (this.record()?.runs ?? []).filter((r) => !r.simulated));

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
