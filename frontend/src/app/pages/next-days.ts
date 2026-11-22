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
  templateUrl: './next-days.html',
  styleUrl: './next-days.scss',
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
