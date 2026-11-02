import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../core/api.service';
import { pct, price, shortDate } from '../core/format';
import { AssetForecast, ForecastView, PriceRange } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { describeError } from '../core/universe-store';
import { HintComponent } from '../shared/hint';

const KEY = 'three';

/** Every asset's likely price range three days from now, 7 times in 10, and how often such ranges held. */
@Component({
  selector: 'app-next-days',
  imports: [RouterLink, HintComponent],
  template: `
    <section class="section intro">
      <h2>{{ horizonLabel() }}: where prices are likely to be</h2>
      <p class="muted">
        For each {{ universe === 'crypto' ? 'coin' : 'stock' }}, the range its price should end in
        {{ universe === 'crypto' ? '3 days (72 hours)' : '3 trading sessions' }} from now, <strong>7 times in 10</strong>.
        The other 3 times it will end outside, which is expected: a range that always held would be too wide to be useful.
      </p>
      <button class="btn" type="button" (click)="refresh()" [disabled]="busy()">
        @if (busy()) { <span class="spinner" aria-hidden="true"></span> {{ message() ?? 'Updating' }} } @else { Update with the latest prices }
      </button>
    </section>

    @if (error(); as e) { <p class="notice error" role="alert">{{ e }}</p> }
    @if (missing()) {
      <section class="empty">
        <h2>No 3-day ranges yet</h2>
        <p>They are made with every analysis. Run one from the top of the page, or update with the latest prices.</p>
      </section>
    }

    @if (view(); as v) {
      @let held = held70();
      <section class="section">
        <div class="facts kpis">
          <div>
            <div class="fact-value" [class.down]="held.value != null && held.value < 0.6">{{ held.value == null ? '–' : pct(held.value, 0) }}</div>
            <div class="fact-label">70% ranges that held <app-hint term="coverage" /></div>
            <div class="fact-note">
              @if (held.value == null) { None scored yet: each is checked 3 days later. }
              @else { {{ held.scored }} {{ held.source === 'live' ? 'live' : 'replayed (simulated)' }} ranges. Goal: 70%. }
            </div>
          </div>
          <div>
            <div class="fact-value">{{ fitted() == null ? '–' : pct(fitted(), 0) }}</div>
            <div class="fact-label">Held when fitted <app-hint term="heldOut" /></div>
            <div class="fact-note">On recent dates kept out of fitting</div>
          </div>
          <div>
            <div class="fact-value">{{ shortDate(v.base_date) }}</div>
            <div class="fact-label">Prices as of</div>
            <div class="fact-note">{{ rows().length }} {{ universe === 'crypto' ? 'coins' : 'stocks' }}</div>
          </div>
        </div>
      </section>

      @if (rows().length) {
        <section class="section">
          <div class="table-wrap">
            <table class="data">
              <thead><tr>
                <th scope="col">Asset</th>
                <th scope="col" class="num">Price now</th>
                <th scope="col" class="bar-col"><span class="sr-only">Range around today's price</span></th>
                <th scope="col" class="num">In 3 days, 7 times in 10 <app-hint term="range70" /></th>
                <th scope="col" class="num">Ranges held <app-hint term="coverage" /></th>
              </tr></thead>
              <tbody>
                @for (row of rows(); track row.asset.symbol) {
                  @let a = row.asset;
                  @let r = row.range;
                  <tr>
                    <td>
                      <a class="asset-link" [routerLink]="['../asset', a.symbol]">{{ a.symbol }}</a>
                      @if (a.picked) { <span class="chip chip-accent">Pick</span> }
                      <div class="small muted name">{{ a.name }}</div>
                    </td>
                    <td class="num">{{ price(a.price) }}</td>
                    <td class="bar-col">
                      <span class="bar" [attr.aria-label]="'From ' + move(r.q15!, a.price) + ' to ' + move(r.q85!, a.price)">
                        <span class="inner" [style.left.%]="pos(r.q15!, a.price)" [style.width.%]="pos(r.q85!, a.price) - pos(r.q15!, a.price)"></span>
                        <span class="now"></span>
                      </span>
                    </td>
                    <td class="num range">
                      {{ price(r.q15) }} – {{ price(r.q85) }}
                      <div class="small faint">{{ move(r.q15!, a.price) }} / {{ move(r.q85!, a.price) }}</div>
                    </td>
                    <td class="num">
                      @if (a.reliability[KEY]?.scored_70) {
                        {{ pct(a.reliability[KEY]?.coverage_70, 0) }}
                        <div class="small faint">of {{ a.reliability[KEY]?.scored_70 }}{{ a.reliability_source === 'simulated' ? ', replayed' : '' }}</div>
                      } @else { <span class="faint">–</span> }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      } @else {
        <p class="muted">These forecasts were made before 3-day ranges existed. Update with the latest prices to get them.</p>
      }

      <section class="section how-computed">
        <h3>How the prediction is computed</h3>
        <ol>
          <li><strong>How much it usually moves.</strong> Each {{ universe === 'crypto' ? 'coin' : 'stock' }}'s recent daily swings,
            weighted towards the last few weeks and blended with its swings over the past year, so one quiet week does
            not make the range too narrow.</li>
          <li><strong>How far 3-day moves really went.</strong> Every past 3-day move of every asset in this market,
            measured in units of that asset's usual swing at the time. These real moves include the occasional big jump
            that a textbook bell curve would underestimate.</li>
          <li><strong>The 70% range.</strong> The middle 70% of those past moves (from the 15th to the 85th percentile),
            scaled by today's swing and centred on today's price. It does not lean up or down: over 3 days, no one can
            reliably tell which way a price will go.</li>
          <li><strong>Checked, not assumed.</strong> When the ranges are fitted, they are tested on recent dates kept
            out of fitting ("Held when fitted"). Then every live range is checked 3 days later ("Ranges held"). If fewer
            than about 6 in 10 hold, the method needs revisiting.</li>
        </ol>
        <p class="small faint">
          Use the range for what it is: how much a price can move, to size a position or decide a stop level.
          It is not a target. The same method gives the 50% and 90% ranges on the <a routerLink="../forecast">Forecast</a> page.
          Research tool, not financial advice.
        </p>
      </section>
    }
  `,
  styles: `
    .intro { padding-top: 2rem; }
    .intro p { margin: 0.5rem 0 1rem; max-width: 60rem; }
    .asset-link { font-weight: 700; text-decoration: none; color: var(--accent); white-space: nowrap; }
    .name { max-width: 14rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .chip { margin-left: 0.4rem; }
    .range { white-space: nowrap; }
    .bar-col { width: 12rem; min-width: 8rem; }
    .bar { position: relative; display: block; height: 14px; }
    .inner { position: absolute; top: 3px; height: 8px; border-radius: 4px; background: var(--accent); }
    .now { position: absolute; left: 50%; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--ink); }
    .how-computed ol { max-width: 60rem; padding-left: 1.25rem; display: grid; gap: 0.6rem; line-height: 1.55; }
    .how-computed p { max-width: 60rem; }
  `,
})
export class NextDaysPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly KEY = KEY;
  readonly view = signal<ForecastView | null>(null);
  readonly missing = signal(false);
  readonly error = signal<string | null>(null);
  readonly busy = signal(false);
  readonly message = signal<string | null>(null);

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.forecast(this.universe).subscribe({
      next: (v) => { this.view.set(v); this.missing.set(false); },
      error: (err) => (err?.status === 404 ? this.missing.set(true) : this.error.set(describeError(err))),
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
          if (j.status === 'failed') { this.busy.set(false); this.message.set(null); this.error.set(j.error ?? 'The update failed'); }
        },
        error: (err) => { this.busy.set(false); this.error.set(describeError(err)); },
      }),
      error: (err) => { this.busy.set(false); this.error.set(describeError(err)); },
    });
  }

  readonly horizonLabel = computed(() =>
    this.view()?.horizons.find((h) => h.key === KEY)?.label ?? (this.universe === 'crypto' ? 'Next 3 days' : 'Next 3 sessions'));

  /** Assets that have a 3-day 70% range, in ranking order */
  readonly rows = computed<{ asset: AssetForecast; range: PriceRange }[]>(() =>
    (this.view()?.assets ?? [])
      .filter((a) => a.three?.q15 != null && a.three?.q85 != null)
      .map((a) => ({ asset: a, range: a.three! })));

  readonly held70 = computed(() => {
    const v = this.view();
    for (const source of ['live', 'simulated'] as const) {
      const r = v?.reliability[source][KEY];
      if (r?.scored_70) return { value: r.coverage_70 ?? null, scored: r.scored_70, source };
    }
    return { value: null as number | null, scored: 0, source: 'live' as const };
  });

  readonly fitted = computed(() => this.view()?.evaluation[KEY]?.coverage_70 ?? null);

  private readonly scale = computed(() => {
    const moves = this.rows().flatMap(({ asset, range }) =>
      [Math.abs(range.q15! / asset.price - 1), Math.abs(range.q85! / asset.price - 1)]);
    return Math.max(0.005, ...moves) * 1.05;
  });

  pos(level: number, base: number): number {
    return Math.max(0, Math.min(100, 50 + ((level / base - 1) / this.scale()) * 50));
  }

  move(level: number, base: number): string {
    return pct(level / base - 1, 1, true);
  }

  readonly pct = pct;
  readonly price = price;
  readonly shortDate = shortDate;
}
