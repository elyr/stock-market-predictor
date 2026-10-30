import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../core/api.service';
import { pct, price, shortDate } from '../core/format';
import { AssetForecast, ForecastView, PriceRange, RangeReliability } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { UniverseStores, describeError } from '../core/universe-store';

type SortKey = 'rank' | 'symbol' | 'width' | 'beat';

@Component({
  selector: 'app-forecast',
  imports: [RouterLink],
  template: `
    <section class="section intro">
      <h2>Where prices may be</h2>
      <p class="muted">
        Nobody can say what a price will be tomorrow: the expected move is tiny compared with the day-to-day noise.
        What can be forecast is how far prices are likely to move. Each range is centred on today's price; the
        darker part is where the price should end up half of the time, the whole bar nine times out of ten.
      </p>
      <div class="controls">
        <div class="switch" role="group" aria-label="Horizon">
          @for (h of view()?.horizons ?? []; track h.key) {
            <button type="button" class="btn" [class.on]="horizon() === h.key" [attr.aria-pressed]="horizon() === h.key"
                    (click)="horizon.set(h.key)">{{ h.label }}</button>
          }
        </div>
        <button class="btn" type="button" (click)="refresh()" [disabled]="busy()">
          @if (busy()) { <span class="spinner" aria-hidden="true"></span> {{ message() ?? 'Updating' }} } @else { Update with the latest prices }
        </button>
      </div>
    </section>

    @if (error(); as e) { <p class="notice error" role="alert">{{ e }}</p> }

    @if (missing()) {
      <section class="empty">
        <h2>No forecast yet</h2>
        <p>Ranges are made with every analysis. Run one from the top of the page, or use the button above.</p>
      </section>
    }

    @if (view(); as v) {
      @let held = held90();
      <section class="section">
        <div class="facts">
          <div>
            <div class="fact-value" [class.down]="warnCoverage(held.value)">{{ held.value === null ? '–' : pct(held.value, 0) }}</div>
            <div class="fact-label">
              @if (held.value === null) {
                Of the 90% ranges held so far. None has been scored yet; each is checked once its window has passed.
              } @else {
                Of {{ held.scored }} {{ held.source === 'live' ? '' : 'replayed (simulated) ' }}90% ranges contained
                the price that followed. The goal is 90%.
              }
            </div>
          </div>
          <div>
            <div class="fact-value">{{ fitted() === null ? '–' : pct(fitted(), 0) }}</div>
            <div class="fact-label">Held on recent dates the model never saw when it was fitted</div>
          </div>
          <div>
            <div class="fact-value">{{ shortDate(v.base_date) }}</div>
            <div class="fact-label">Prices the ranges start from ({{ v.assets.length }} {{ universe === 'crypto' ? 'coins' : 'stocks' }})</div>
          </div>
        </div>
      </section>

      <section class="section">
        <div class="table-wrap">
          <table class="data">
            <thead><tr>
              <th scope="col"><button type="button" class="sort" (click)="sortBy('symbol')">Asset{{ arrow('symbol') }}</button></th>
              <th scope="col" class="num">Price now</th>
              <th scope="col" class="num">Likely (half the time)</th>
              <th scope="col" class="bar-col"><span class="sr-only">Range around today's price</span></th>
              <th scope="col" class="num"><button type="button" class="sort" (click)="sortBy('width')">9 times in 10{{ arrow('width') }}</button></th>
              <th scope="col" class="num"><button type="button" class="sort" (click)="sortBy('beat')">Beats the field{{ arrow('beat') }}</button></th>
              <th scope="col" class="num">Ranges held</th>
            </tr></thead>
            <tbody>
              @for (a of rows(); track a.symbol) {
                @let r = rangeOf(a);
                <tr>
                  <td>
                    <a class="asset-link" [routerLink]="['../asset', a.symbol]">{{ a.symbol }}</a>
                    @if (a.picked) { <span class="chip chip-accent">Pick</span> }
                    <div class="small muted name">{{ a.name }}</div>
                  </td>
                  <td class="num">{{ price(a.price) }}</td>
                  @if (r) {
                    <td class="num range">{{ price(r.q25) }} – {{ price(r.q75) }}</td>
                    <td class="bar-col">
                      <span class="bar" [attr.aria-label]="'From ' + move(r.q05, a.price) + ' to ' + move(r.q95, a.price)">
                        <span class="outer" [style.left.%]="pos(r.q05, a.price)" [style.width.%]="pos(r.q95, a.price) - pos(r.q05, a.price)"></span>
                        <span class="inner" [style.left.%]="pos(r.q25, a.price)" [style.width.%]="pos(r.q75, a.price) - pos(r.q25, a.price)"></span>
                        <span class="now"></span>
                      </span>
                    </td>
                    <td class="num range">
                      {{ price(r.q05) }} – {{ price(r.q95) }}
                      <div class="small faint">{{ move(r.q05, a.price) }} / {{ move(r.q95, a.price) }}</div>
                    </td>
                  } @else {
                    <td class="num">–</td><td></td><td class="num">–</td>
                  }
                  <td class="num">{{ pct(a.beat_probability, 0) }}</td>
                  <td class="num">
                    @if (assetHeld(a); as h) {
                      <span [class.down]="warnCoverage(h.coverage_90)">{{ pct(h.coverage_90, 0) }}</span>
                      <div class="small faint">of {{ h.scored }}{{ a.reliability_source === 'simulated' ? ', replayed' : '' }}</div>
                    } @else { <span class="faint">–</span> }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
        <p class="small faint note">
          "Beats the field" is the model's chance that the asset does better than the average
          {{ universe === 'crypto' ? 'coin' : 'stock' }} over {{ beatDays() }} days. "Ranges held" is how often this
          asset's past 90% ranges contained the outcome{{ anySimulated() ? '; "replayed" means ranges made on past dates for the demo, not before the fact' : '' }}.
          Ranges come from each asset's recent volatility and how far prices of this market have moved relative to it.
          Research tool, not financial advice.
        </p>
      </section>
    }
  `,
  styles: `
    .intro { padding-top: 2rem; }
    .intro p { margin-top: 0.5rem; max-width: 60rem; }
    .controls { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; justify-content: space-between; margin-top: 1rem; }
    .switch { display: inline-flex; }
    .switch .btn { border-radius: 0; }
    .switch .btn:first-child { border-radius: 6px 0 0 6px; }
    .switch .btn:last-child { border-radius: 0 6px 6px 0; margin-left: -1px; }
    .switch .btn.on { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
    .asset-link { font-weight: 700; text-decoration: none; color: var(--accent); white-space: nowrap; }
    .name { max-width: 14rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .chip { margin-left: 0.4rem; }
    .range { white-space: nowrap; }
    .sort { font: inherit; font-weight: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; }
    .sort:hover { color: var(--accent); }
    .bar-col { width: 11rem; min-width: 8rem; }
    .bar { position: relative; display: block; height: 14px; }
    .outer, .inner { position: absolute; top: 3px; height: 8px; border-radius: 4px; }
    .outer { background: var(--accent-wash); outline: 1px solid var(--accent); outline-offset: -1px; opacity: 0.8; }
    .inner { background: var(--accent); }
    .now { position: absolute; left: 50%; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--ink); }
    .note { margin-top: 0.75rem; max-width: 60rem; }
  `,
})
export class ForecastPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly store = inject(UniverseStores).get(this.universe);
  readonly view = signal<ForecastView | null>(null);
  readonly missing = signal(false);
  readonly error = signal<string | null>(null);
  readonly busy = signal(false);
  readonly message = signal<string | null>(null);
  readonly horizon = signal<'day' | 'week'>('week');
  readonly sort = signal<{ key: SortKey; descending: boolean }>({ key: 'rank', descending: false });

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.forecast(this.universe).subscribe({
      next: (v) => { this.view.set(v); this.missing.set(false); },
      error: (err) => {
        if (err?.status === 404) this.missing.set(true);
        else this.error.set(describeError(err));
      },
    });
  }

  refresh(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.refreshForecast(this.universe).subscribe({
      next: (job) => this.api.watchJob(job.id).subscribe({
        next: (j) => {
          this.message.set(j.message);
          if (j.status === 'succeeded') { this.busy.set(false); this.message.set(null); this.load(); }
          if (j.status === 'failed') { this.busy.set(false); this.message.set(null); this.error.set(j.error ?? 'The forecast failed'); }
        },
        error: (err) => { this.busy.set(false); this.error.set(describeError(err)); },
      }),
      error: (err) => { this.busy.set(false); this.error.set(describeError(err)); },
    });
  }

  /** Largest move shown, so every bar uses the same scale for the chosen horizon */
  private readonly scale = computed(() => {
    const v = this.view();
    const key = this.horizon();
    if (!v) return 0.1;
    const moves = v.assets.flatMap((a) => {
      const r = a[key];
      return r ? [Math.abs(r.q05 / a.price - 1), Math.abs(r.q95 / a.price - 1)] : [];
    });
    return Math.max(0.005, ...moves) * 1.05;
  });

  readonly rows = computed<AssetForecast[]>(() => {
    const v = this.view();
    if (!v) return [];
    const { key, descending } = this.sort();
    const value = (a: AssetForecast): number | string => {
      if (key === 'symbol') return a.symbol;
      if (key === 'beat') return a.beat_probability ?? -1;
      if (key === 'width') { const r = this.rangeOf(a); return r ? (r.q95 - r.q05) / a.price : -1; }
      return a.rank ?? 1e9;
    };
    return [...v.assets].sort((x, y) => {
      const a = value(x), b = value(y);
      const order = a < b ? -1 : a > b ? 1 : 0;
      return descending ? -order : order;
    });
  });

  readonly held90 = computed(() => {
    const v = this.view();
    const key = this.horizon();
    const live = v?.reliability.live[key];
    if (live && live.scored > 0) return { value: live.coverage_90, scored: live.scored, source: 'live' as const };
    const simulated = v?.reliability.simulated[key];
    if (simulated && simulated.scored > 0) {
      return { value: simulated.coverage_90, scored: simulated.scored, source: 'simulated' as const };
    }
    return { value: null, scored: 0, source: 'live' as const };
  });

  readonly fitted = computed(() => this.view()?.evaluation[this.horizon()]?.coverage_90 ?? null);
  readonly beatDays = computed(() => this.store.info()?.horizon_days ?? 5);
  readonly anySimulated = computed(() => (this.view()?.assets ?? []).some((a) => a.reliability_source === 'simulated'));

  rangeOf(a: AssetForecast): PriceRange | undefined {
    return a[this.horizon()];
  }

  assetHeld(a: AssetForecast): RangeReliability | null {
    const r = a.reliability[this.horizon()];
    return r && r.scored > 0 ? r : null;
  }

  sortBy(key: SortKey): void {
    const current = this.sort();
    this.sort.set({ key, descending: current.key === key ? !current.descending : key !== 'symbol' && key !== 'rank' });
  }

  arrow(key: SortKey): string {
    const current = this.sort();
    return current.key === key ? (current.descending ? ' ↓' : ' ↑') : '';
  }

  /** Position on the bar, in percent: today's price in the middle */
  pos(level: number, base: number): number {
    return Math.max(0, Math.min(100, 50 + ((level / base - 1) / this.scale()) * 50));
  }

  move(level: number, base: number): string {
    return pct(level / base - 1, 1, true);
  }

  warnCoverage(value: number | null | undefined): boolean {
    return value != null && value < 0.8;
  }

  readonly pct = pct;
  readonly price = price;
  readonly shortDate = shortDate;
}
