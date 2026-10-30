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
  template: `
    <section class="section intro">
      <h2>Which way is the turbulence heading?</h2>
      <p class="muted">
        The size of moves is far more predictable than their direction: calm follows calm, rough follows rough.
        Use this to size positions or to expect bigger swings over the next {{ view()?.horizon_days ?? 5 }} days, not to pick direction.
      </p>
    </section>

    @if (error(); as e) { <p class="notice error" role="alert">{{ e }}</p> }

    @if (view(); as v) {
      @if (v.model; as m) {
        <section class="section">
          <div class="facts">
            <div><div class="fact-value">{{ pct(m.accuracy, 0) }}</div><div class="fact-label">Right calls on rising or falling <app-hint term="accuracy" /></div>
              <div class="fact-note">Always guessing the common case: {{ pct(m.base_rate, 0) }}</div></div>
            <div><div class="fact-value">{{ num(m.auc, 2) }}</div><div class="fact-label">AUC <app-hint term="auc" /></div>
              <div class="fact-note">0.5 is a coin flip</div></div>
            <div><div class="fact-value">{{ pct(m.r2_model, 0) }}</div><div class="fact-label">Variation explained <app-hint term="r2" /></div>
              <div class="fact-note">vs {{ pct(m.r2_naive, 0) }} assuming no change</div></div>
          </div>
        </section>
        <section class="section">
          <div class="table-wrap">
            <table class="data">
              <thead><tr>
                <th scope="col">Asset</th><th scope="col" class="num">Price</th>
                <th scope="col" class="num">Volatility now <app-hint term="volatility" /></th><th scope="col">Next {{ v.horizon_days }} days</th>
                <th scope="col" class="num">Forecast <app-hint term="volForecast" /></th><th scope="col" class="num">Chance it rises <app-hint term="volUp" /></th>
              </tr></thead>
              <tbody>
                @for (a of v.assets; track a.symbol) {
                  <tr>
                    <td><a class="asset-link" [routerLink]="['../asset', a.symbol]">{{ a.symbol }}</a> <span class="muted">{{ a.company_name }}</span></td>
                    <td class="num">{{ price(a.current_price) }}</td>
                    <td class="num">{{ pct(a.volatility, 0) }}</td>
                    <td>
                      <span class="range" [attr.aria-label]="'From ' + pct(a.volatility, 0) + ' to ' + pct(a.vol_forecast, 0)">
                        <span class="dot now" [style.left.%]="scale(a.volatility)"></span>
                        <span class="dot next" [class.rising]="(a.vol_forecast ?? 0) > (a.volatility ?? 0)" [style.left.%]="scale(a.vol_forecast)"></span>
                      </span>
                    </td>
                    <td class="num">{{ pct(a.vol_forecast, 0) }}</td>
                    <td class="num" [class.down]="(a.vol_up_probability ?? 0) > 0.6">{{ pct(a.vol_up_probability, 0) }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          <p class="small faint note">Annualized. Hollow dot: last 20 days; filled dot: forecast. Forecast as of {{ shortDate(v.data_date) }}.</p>
        </section>
      } @else {
        <section class="empty"><h2>No forecast yet</h2><p>Run an analysis from the top of the page; the volatility model trains alongside the ranking model.</p></section>
      }
    }
  `,
  styles: `
    .intro { padding-top: 2rem; }
    .intro p { margin-top: 0.5rem; }
    .asset-link { font-weight: 700; text-decoration: none; color: var(--accent); }
    .range { position: relative; display: block; width: 10rem; height: 12px; border-bottom: 1px solid var(--grid-strong); }
    .dot { position: absolute; top: 2px; width: 9px; height: 9px; margin-left: -4px; border-radius: 50%; }
    .now { border: 2px solid var(--ink-faint); background: var(--paper); }
    .next { background: var(--up); }
    .next.rising { background: var(--down); }
    .note { margin-top: 0.75rem; }
  `,
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
