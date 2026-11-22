import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../core/api.service';
import { num, pct, price, shortDate } from '../core/format';
import { VolatilityView } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { UniverseStores, describeError } from '../core/universe-store';
import { HintComponent } from '../shared/hint';

@Component({
  selector: 'app-volatility',
  imports: [RouterLink, HintComponent],
  templateUrl: './volatility.html',
  styleUrl: './volatility.scss',
})
export class VolatilityPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly store = inject(UniverseStores).get(this.universe);
  readonly view = signal<VolatilityView | null>(null);
  readonly error = signal<string | null>(null);
  private max = 1;

  ngOnInit(): void {
    this.api.volatility(this.universe).subscribe({
      next: (v) => {
        this.max = Math.max(0.01, ...v.assets.flatMap((a) => [a.volatility ?? 0, a.vol_forecast ?? 0])) * 1.05;
        this.view.set(v);
      },
      error: (err) => this.error.set(describeError(err)),
    });
  }

  scale(value: number | null): number {
    return Math.min(100, ((value ?? 0) / this.max) * 100);
  }

  readonly pct = pct;
  readonly num = num;
  readonly price = price;
  readonly shortDate = shortDate;
}
