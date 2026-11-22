import { Component, computed, inject } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';

import { AlertsState } from '../core/alerts-state';

import { pct, price, shortDate } from '../core/format';
import { injectUniverse } from '../core/route-universe';
import { UniverseStores } from '../core/universe-store';
import { HintComponent } from '../shared/hint';

/** Header and frame for one dashboard; owns that dashboard's accent colour. */
@Component({
  selector: 'app-universe-layout',
  imports: [RouterOutlet, RouterLink, HintComponent],
  host: { '[class]': "'theme-' + universe" },
  templateUrl: './universe-layout.html',
  styleUrl: './universe-layout.scss',
})
export class UniverseLayout {
  readonly universe = injectUniverse();
  readonly store = inject(UniverseStores).get(this.universe);
  readonly alerts = inject(AlertsState);

  readonly description = computed(() => {
    const info = this.store.info();
    if (!info) return '';
    const what = 'assets';
    const days = info.key === 'crypto' ? `${info.horizon_days} days` : `${info.horizon_days} trading days`;
    return info.target === 'relative'
      ? `Ranks ${info.symbol_count} ${what} by how likely each is to beat the others over the next ${days}.`
      : `Ranks ${info.symbol_count} ${what} by how likely each is to rise over the next ${days}.`;
  });

  readonly pct = pct;
  readonly price = price;
  readonly shortDate = shortDate;
}
