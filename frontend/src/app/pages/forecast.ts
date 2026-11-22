import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../core/api.service';
import { pct, price, shortDate } from '../core/format';
import { AssetForecast, ForecastView, HorizonKey, PriceRange, RangeReliability } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { UniverseStores, describeError } from '../core/universe-store';
import { HintComponent } from '../shared/hint';

type SortKey = 'rank' | 'symbol' | 'width' | 'beat';

@Component({
  selector: 'app-forecast',
  imports: [RouterLink, HintComponent],
  templateUrl: './forecast.html',
  styleUrl: './forecast.scss',
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
  readonly horizon = signal<HorizonKey>('week');
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
