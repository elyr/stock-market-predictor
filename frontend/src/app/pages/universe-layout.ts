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
  template: `
    <header class="head">
      <div class="title">
        <h1>{{ store.info()?.label ?? (universe === 'crypto' ? 'Crypto' : 'US Stocks') }}</h1>
        <p class="muted">{{ description() }}</p>
      </div>
      <div class="actions">
        <span class="run">
          <button class="btn btn-primary" type="button" (click)="store.runAnalysis()" [disabled]="store.running()">
            @if (store.running()) { <span class="spinner" aria-hidden="true"></span> Running } @else { Run analysis }
          </button>
          <app-hint label="Run analysis" text="Fetches the latest prices, retrains the model, ranks every asset, suggests a portfolio and updates the price ranges. Takes a minute or two; you can keep browsing." />
        </span>
        @if (alerts.count(universe).total; as unread) {
          <a class="alert-link small" routerLink="alerts" [class.critical]="alerts.count(universe).critical">
            {{ unread }} new {{ unread === 1 ? 'alert' : 'alerts' }}
          </a>
        }
        <p class="small faint status" aria-live="polite">
          @if (store.running()) {
            {{ store.job()?.message }}
          } @else if (store.analysis(); as a) {
            Prices as of {{ shortDate(a.run.data_date) }}
          }
        </p>
      </div>
    </header>

    @if (store.market().length) {
      <ul class="tape" aria-label="Benchmarks">
        @for (item of store.market(); track item.symbol) {
          <li>
            <span class="tape-name">{{ item.name }}</span>
            <span>{{ price(item.price) }}</span>
            <span [class.up]="item.change_pct > 0" [class.down]="item.change_pct < 0">{{ pct(item.change_pct / 100, 2, true) }}</span>
          </li>
        }
      </ul>
    }

    @if (store.job()?.status === 'failed') {
      <p class="notice error page">The last run failed: {{ store.job()?.error }}</p>
    }
    @if (store.error(); as error) {
      <p class="notice error page" role="alert">{{ error }}</p>
    }

    <div class="page"><router-outlet /></div>
  `,
  styles: `
    :host { display: block; }
    .head { display: flex; justify-content: space-between; align-items: flex-end; gap: 1.5rem; flex-wrap: wrap;
      padding: 2rem clamp(1rem, 4vw, 3rem) 1.25rem; border-bottom: 1px solid var(--grid); }
    .title p { margin-top: 0.4rem; }
    .title h1 { color: var(--ink); border-left: 6px solid var(--accent); padding-left: 0.75rem; margin-left: -1.1rem; }
    .actions { display: grid; justify-items: end; gap: 0.35rem; }
    .status { min-height: 1.2em; }
    .run { display: inline-flex; align-items: center; gap: 0.25rem; }
    .alert-link { color: var(--accent); font-weight: 600; text-decoration: none; }
    .alert-link.critical { color: var(--down); }
    .alert-link:hover { text-decoration: underline; }
    .tape { list-style: none; margin: 0; padding: 0.6rem clamp(1rem, 4vw, 3rem); display: flex; gap: 2rem;
      flex-wrap: wrap; font-size: var(--step--1); border-bottom: 1px solid var(--grid); background: var(--paper-raised); }
    .tape li { display: flex; gap: 0.6rem; }
    .tape-name { color: var(--ink-soft); }
    .page { padding: 0 clamp(1rem, 4vw, 3rem) 3rem; max-width: 84rem; }
    .notice.page { margin: 1rem clamp(1rem, 4vw, 3rem) 0; }
    @media (max-width: 860px) { .title h1 { margin-left: 0; } .actions { justify-items: start; } }
  `,
})
export class UniverseLayout {
  readonly universe = injectUniverse();
  readonly store = inject(UniverseStores).get(this.universe);
  readonly alerts = inject(AlertsState);

  readonly description = computed(() => {
    const info = this.store.info();
    if (!info) return '';
    const what = info.key === 'crypto' ? 'coins' : 'stocks';
    const days = info.key === 'crypto' ? `${info.horizon_days} days` : `${info.horizon_days} trading days`;
    return info.target === 'relative'
      ? `Ranks ${info.symbol_count} ${what} by how likely each is to beat the others over the next ${days}.`
      : `Ranks ${info.symbol_count} ${what} by how likely each is to rise over the next ${days}.`;
  });

  readonly pct = pct;
  readonly price = price;
  readonly shortDate = shortDate;
}
