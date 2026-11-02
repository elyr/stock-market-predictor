import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../core/api.service';
import { evidence, num, pct, price, shortDate } from '../core/format';
import { LongTermView } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { describeError } from '../core/universe-store';
import { EvidenceMeterComponent } from '../shared/evidence-meter';
import { HintComponent } from '../shared/hint';
import { ScoreBarComponent } from '../shared/score-bar';

/** The ranking for the month ahead, from a second model, with its own evidence. */
@Component({
  selector: 'app-long-term',
  imports: [RouterLink, EvidenceMeterComponent, HintComponent, ScoreBarComponent],
  template: `
    <section class="section intro">
      <h2>The month ahead</h2>
      <p class="muted">
        Over a few days, prices are mostly noise. Over a month, well-known effects such as momentum, low volatility and
        prices near their yearly high have more room to show. A second model, trained on the same inputs, ranks every
        {{ universe === 'crypto' ? 'coin' : 'stock' }} for about {{ view()?.horizon_days ?? (universe === 'crypto' ? 30 : 21) }}
        {{ universe === 'crypto' ? 'days' : 'trading days' }} ahead.
      </p>
    </section>

    @if (error(); as e) { <p class="notice error" role="alert">{{ e }}</p> }
    @if (missing()) {
      <section class="empty">
        <h2>No long-term ranking yet</h2>
        <p>It is trained with every analysis. Run one from the top of the page.</p>
      </section>
    }

    @if (view(); as v) {
      @let q = v.model_quality;
      <section class="section">
        <div class="facts kpis">
          <div>
            <div [class]="'fact-value tone-' + verdict().tone">{{ q.ic_mean == null ? '–' : num(q.ic_mean, 3, true) }}</div>
            <div class="fact-label">Model skill (rank IC) <app-hint term="ic" /></div>
            <div class="fact-note">{{ verdict().label }} (t = {{ num(q.ic_t_stat, 1) }})</div>
          </div>
          <div>
            <div class="fact-value">{{ v.horizon_days }} {{ universe === 'crypto' ? 'days' : 'sessions' }}</div>
            <div class="fact-label">How far ahead</div>
            <div class="fact-note">The short-term model looks {{ v.short_horizon_days }} ahead</div>
          </div>
          <div>
            <div class="fact-value">{{ shortDate(v.data_date) }}</div>
            <div class="fact-label">Prices as of</div>
            <div class="fact-note">{{ v.assets.length }} {{ universe === 'crypto' ? 'coins' : 'stocks' }} ranked</div>
          </div>
        </div>
      </section>

      @if (q.ic_mean != null) {
        <section class="section">
          <h3>Is it better than luck? <app-hint term="luckBand" /></h3>
          <app-evidence-meter [ic]="q.ic_mean!" [t]="q.ic_t_stat" [icStd]="q.ic_std" [days]="q.ic_days ?? 0"
                              [periods]="q.ic_independent_periods" [positiveShare]="q.ic_positive_share" />
          <p class="small faint">The evidence counts about {{ independent() }} independent {{ v.horizon_days }}-day periods: overlapping months are not counted twice.</p>
        </section>
      }

      <section class="section two-col">
        <div>
          <h3>Ranking for the month ahead</h3>
          <div class="table-wrap">
            <table class="data">
              <thead><tr>
                <th scope="col">Rank</th><th scope="col">Asset</th>
                <th scope="col">Long-term score <app-hint term="longTerm" /></th>
                <th scope="col" class="num">Chance to beat the field <app-hint term="beat" /></th>
                <th scope="col" class="num">Short-term rank</th>
                <th scope="col" class="num">Price</th>
              </tr></thead>
              <tbody>
                @for (a of shown(); track a.symbol) {
                  <tr>
                    <td class="rank">{{ a.rank }}</td>
                    <td>
                      <a class="asset-link" [routerLink]="['../asset', a.symbol]">{{ a.symbol }}</a>
                      <div class="small muted name">{{ a.name }}</div>
                    </td>
                    <td><app-score-bar [value]="a.score" label="Long-term score" /></td>
                    <td class="num">{{ pct(a.probability, 0) }}</td>
                    <td class="num">{{ a.short_rank ?? '–' }}</td>
                    <td class="num">{{ price(a.price) }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          @if (v.assets.length > 15) {
            <button class="btn btn-quiet" type="button" (click)="all.set(!all())" [attr.aria-expanded]="all()">
              {{ all() ? 'Show the top 15' : 'Show all ' + v.assets.length }}
            </button>
          }
        </div>
        <div>
          <h3>What history rewarded <app-hint term="learnedWeights" /></h3>
          <ul class="weights">
            @for (w of v.weights; track w.feature) {
              <li>
                <span class="w-label">{{ w.label }}</span>
                <span class="w-axis"><span class="w-bar" [class.pos]="w.weight > 0" [class.neg]="w.weight < 0"
                  [style.width.%]="(abs(w.weight) / maxWeight()) * 50"></span></span>
              </li>
            }
          </ul>
          <p class="small faint">Bars to the right helped, to the left hurt, over the month that followed.</p>
        </div>
      </section>
      <p class="small faint">Research tool, not financial advice.</p>
    }
  `,
  styles: `
    .intro { padding-top: 2rem; }
    .intro p { margin-top: 0.5rem; max-width: 60rem; }
    .two-col { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 2rem; }
    .asset-link { font-weight: 700; text-decoration: none; color: var(--accent); }
    .name { max-width: 14rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .rank { color: var(--ink-faint); }
    .weights { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.45rem; }
    .weights li { display: grid; grid-template-columns: minmax(8rem, 1fr) 1fr; gap: 0.75rem; align-items: center; font-size: var(--step--1); }
    .w-axis { position: relative; height: 10px; border-left: 1px solid transparent; }
    .w-axis::before { content: ''; position: absolute; left: 50%; top: -3px; bottom: -3px; width: 1px; background: var(--grid-strong); }
    .w-bar { position: absolute; top: 1px; height: 8px; border-radius: 4px; }
    .w-bar.pos { left: 50%; background: var(--up); }
    .w-bar.neg { right: 50%; background: var(--down); }
    @media (max-width: 860px) { .two-col { grid-template-columns: 1fr; } }
  `,
})
export class LongTermPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly view = signal<LongTermView | null>(null);
  readonly missing = signal(false);
  readonly error = signal<string | null>(null);
  readonly all = signal(false);

  ngOnInit(): void {
    this.api.longTerm(this.universe).subscribe({
      next: (v) => this.view.set(v),
      error: (err) => (err?.status === 404 ? this.missing.set(true) : this.error.set(describeError(err))),
    });
  }

  readonly verdict = computed(() => evidence(this.view()?.model_quality.ic_t_stat));
  readonly shown = computed(() => (this.all() ? this.view()?.assets ?? [] : (this.view()?.assets ?? []).slice(0, 15)));
  readonly maxWeight = computed(() => Math.max(1e-9, ...(this.view()?.weights ?? []).map((w) => Math.abs(w.weight))));
  readonly independent = computed(() => {
    const q = this.view()?.model_quality;
    return Math.round(q?.ic_independent_periods ?? q?.ic_days ?? 0);
  });

  abs(value: number): number {
    return Math.abs(value);
  }

  readonly num = num;
  readonly pct = pct;
  readonly price = price;
  readonly shortDate = shortDate;
}
