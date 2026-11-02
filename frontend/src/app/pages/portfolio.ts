import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ChartConfiguration } from 'chart.js';

import { ApiService } from '../core/api.service';
import { pct, price, shortDate } from '../core/format';
import { NewTransaction, PortfolioView, Position } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { UniverseStores, describeError } from '../core/universe-store';
import { ChartComponent, baseOptions, themeColors } from '../shared/chart';
import { HintComponent } from '../shared/hint';

/** Your own holdings: record trades, see gains, risk and what needs attention. */
@Component({
  selector: 'app-portfolio',
  imports: [FormsModule, RouterLink, ChartComponent, HintComponent],
  template: `
    <section class="section intro">
      <h2>My portfolio</h2>
      <p class="muted">
        Record what you buy and sell. Ledger works out what you hold, how it did compared with
        {{ view()?.benchmark_label ?? 'the market' }}, how risky it is, and what needs your attention.
        Prices are in US dollars; nothing leaves this computer.
      </p>
    </section>

    @if (error(); as e) { <p class="notice error" role="alert">{{ e }}</p> }
    @if (!view() && !error()) { <p class="muted"><span class="spinner" aria-hidden="true"></span> Loading your portfolio</p> }

    @if (view(); as v) {
      @if (v.summary; as s) {
        <section class="section">
          <div class="facts kpis">
            <div>
              <div class="fact-value">{{ money(s.value) }}</div>
              <div class="fact-label">Portfolio value <app-hint term="portfolioValue" /></div>
              <div class="fact-note">{{ s.positions }} {{ s.positions === 1 ? 'holding' : 'holdings' }}, prices of {{ shortDate(s.as_of) }}</div>
            </div>
            <div>
              <div class="fact-value" [class.up]="s.gain > 0" [class.down]="s.gain < 0">{{ signedMoney(s.gain) }}</div>
              <div class="fact-label">Gain or loss <app-hint term="totalGain" /></div>
              <div class="fact-note">{{ pct(s.gain_pct, 1, true) }} since {{ shortDate(s.since) }}</div>
            </div>
            <div>
              <div class="fact-value" [class.up]="(s.vs_benchmark ?? 0) > 0" [class.down]="(s.vs_benchmark ?? 0) < 0">
                {{ s.vs_benchmark == null ? '–' : signedMoney(s.vs_benchmark) }}</div>
              <div class="fact-label">Compared with the benchmark <app-hint term="vsBenchmark" /></div>
              <div class="fact-note">Same money in {{ v.benchmark_label }}: {{ money(s.benchmark_value) }}</div>
            </div>
            <div>
              <div class="fact-value" [class.down]="(s.volatility ?? 0) > v.rules.max_volatility">{{ s.risk_label ?? '–' }}</div>
              <div class="fact-label">Risk level <app-hint term="riskLevel" /></div>
              <div class="fact-note">Swings about {{ pct(s.volatility, 0) }} a year (your limit {{ pct(v.rules.max_volatility, 0) }})</div>
            </div>
            @if (s.next_week; as w) {
              <div>
                <div class="fact-value range-value">{{ money(w.low) }} – {{ money(w.high) }}</div>
                <div class="fact-label">Next week, likely <app-hint term="nextWeekValue" /></div>
                <div class="fact-note">Roughly 9 times in 10</div>
              </div>
            }
          </div>
        </section>

        <section class="section">
          <h3>What needs your attention</h3>
          @if (v.warnings.length) {
            <ul class="warnings">
              @for (w of v.warnings; track w.message) {
                <li [class]="'warning level-' + w.level">
                  <span class="badge-level" aria-hidden="true">{{ w.level === 'high' ? '!' : w.level === 'medium' ? '•' : 'i' }}</span>
                  <span><span class="sr-only">{{ levelName(w.level) }}: </span>{{ w.message }}</span>
                </li>
              }
            </ul>
          } @else {
            <p class="all-clear">Nothing breaks your rules today. No action needed.</p>
          }
          <p class="small faint">
            Your rules: at most {{ pct(v.rules.max_position, 0) }} in one holding,
            @if (universe === 'stocks') { {{ pct(v.rules.max_sector, 0) }} in one sector, }
            yearly swings under {{ pct(v.rules.max_volatility, 0) }}, at least {{ v.rules.min_positions }} holdings.
            Change them under <code>risk</code> in config/config.yaml.
          </p>
        </section>

        <section class="section">
          <h3>Holdings</h3>
          <div class="table-wrap">
            <table class="data">
              <thead><tr>
                <th scope="col">Asset</th>
                <th scope="col" class="num">Quantity</th>
                <th scope="col" class="num">Average cost <app-hint term="averageCost" /></th>
                <th scope="col" class="num">Price</th>
                <th scope="col" class="num">Value</th>
                <th scope="col">Share of portfolio <app-hint term="holdingWeight" /></th>
                <th scope="col" class="num">Gain</th>
                <th scope="col" class="num">Model view <app-hint term="beat" /></th>
                <th scope="col" class="num">Next week <app-hint term="range90" /></th>
              </tr></thead>
              <tbody>
                @for (p of held(); track p.symbol) {
                  <tr>
                    <td>
                      <a class="asset-link" [routerLink]="['../asset', p.symbol]">{{ p.symbol }}</a>
                      <div class="small muted name">{{ p.name }}{{ p.sector ? ' · ' + p.sector : '' }}</div>
                    </td>
                    <td class="num">{{ qty(p.quantity) }}</td>
                    <td class="num">{{ price(p.average_cost) }}</td>
                    <td class="num">{{ price(p.price) }}</td>
                    <td class="num strong">{{ money(p.value) }}</td>
                    <td>
                      <span class="weight" [class.over]="p.weight > v.rules.max_position">
                        <span class="weight-track"><span class="weight-fill" [style.width.%]="p.weight * 100"></span></span>
                        <span class="weight-label">{{ pct(p.weight, 0) }}</span>
                      </span>
                    </td>
                    <td class="num" [class.up]="p.unrealized > 0" [class.down]="p.unrealized < 0">
                      {{ signedMoney(p.unrealized) }}
                      <div class="small">{{ pct(p.unrealized_pct, 1, true) }}</div>
                    </td>
                    <td class="num">
                      @if (p.rank) {
                        {{ pct(p.beat_probability, 0) }}
                        <div class="small faint">rank {{ p.rank }} of {{ p.universe_size }}</div>
                      } @else { <span class="faint">–</span> }
                    </td>
                    <td class="num range">
                      @if (p.week_range; as r) { {{ price(r.low) }} – {{ price(r.high) }} } @else { <span class="faint">–</span> }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          @if (closed().length) {
            <p class="small muted">
              Sold out of: @for (p of closed(); track p.symbol; let last = $last) {
                {{ p.symbol }} ({{ signedMoney(p.realized) }}){{ last ? '.' : ', ' }}
              }
              Taken so far in total: {{ signedMoney(s.realized) }} <app-hint term="realized" />
            </p>
          }
        </section>

        @if (historyChart(); as c) {
          <section class="section two-col">
            <div>
              <h3>Your portfolio against {{ v.benchmark_label }}</h3>
              <p class="muted small">The benchmark line received exactly the money you put in and took out, on the same days.</p>
              <app-chart [config]="c" [height]="260" label="Portfolio value against the benchmark" />
            </div>
            @if (universe === 'stocks' && v.sectors.length > 1) {
              <div>
                <h3>By sector</h3>
                <ul class="sectors">
                  @for (sec of v.sectors; track sec.sector) {
                    <li>
                      <span class="sector-name">{{ sec.sector }}</span>
                      <span class="weight" [class.over]="sec.weight > v.rules.max_sector">
                        <span class="weight-track"><span class="weight-fill" [style.width.%]="sec.weight * 100"></span></span>
                        <span class="weight-label">{{ pct(sec.weight, 0) }}</span>
                      </span>
                    </li>
                  }
                </ul>
              </div>
            }
          </section>
        }
      } @else {
        <section class="empty">
          <h2>No trades recorded yet</h2>
          <p>Add your first buy below. You can enter past trades with their real date and price: the history and
            the comparison with the benchmark start from your first trade.</p>
        </section>
      }

      <section class="section">
        <h3>Record a trade</h3>
        <form class="trade" (ngSubmit)="submit()" #f="ngForm">
          <div class="field">
            <label for="tx-side">Buy or sell</label>
            <select id="tx-side" name="side" [(ngModel)]="form.side">
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </div>
          <div class="field">
            <label for="tx-symbol">{{ universe === 'crypto' ? 'Coin' : 'Stock' }}</label>
            <input id="tx-symbol" name="symbol" [(ngModel)]="form.symbol" list="tx-symbols" required
                   autocomplete="off" [placeholder]="universe === 'crypto' ? 'BTC-USD' : 'AAPL'" (change)="suggestPrice()">
            <datalist id="tx-symbols">
              @for (s of v.symbols; track s) { <option [value]="s"></option> }
            </datalist>
          </div>
          <div class="field">
            <label for="tx-date">Date</label>
            <input id="tx-date" name="trade_date" type="date" [(ngModel)]="form.trade_date" [max]="today" required>
          </div>
          <div class="field">
            <label for="tx-qty">Quantity</label>
            <input id="tx-qty" name="quantity" type="number" min="0" step="any" [(ngModel)]="form.quantity" required>
          </div>
          <div class="field">
            <label for="tx-price">Price (USD)</label>
            <input id="tx-price" name="price" type="number" min="0" step="any" [(ngModel)]="form.price" required>
          </div>
          <div class="field">
            <label for="tx-fees">Fees (USD)</label>
            <input id="tx-fees" name="fees" type="number" min="0" step="any" [(ngModel)]="form.fees">
          </div>
          <div class="field note-field">
            <label for="tx-note">Note (optional)</label>
            <input id="tx-note" name="note" maxlength="500" [(ngModel)]="form.note" placeholder="Why you made this trade">
          </div>
          <div class="submit">
            <button class="btn btn-primary" type="submit" [disabled]="saving()">
              @if (saving()) { <span class="spinner" aria-hidden="true"></span> Saving } @else { Add trade }
            </button>
          </div>
        </form>
        @if (formError(); as e) { <p class="notice error" role="alert">{{ e }}</p> }
        @if (saved(); as m) { <p class="small muted" aria-live="polite">{{ m }}</p> }
      </section>

      @if (v.transactions.length) {
        <section class="section">
          <div class="section-head">
            <h3>History of your trades</h3>
            <a class="btn btn-quiet" [href]="csvUrl" download>Download as CSV</a>
          </div>
          <div class="table-wrap">
            <table class="data">
              <thead><tr>
                <th scope="col">Date</th><th scope="col">Trade</th><th scope="col" class="num">Quantity</th>
                <th scope="col" class="num">Price</th><th scope="col" class="num">Amount</th><th scope="col">Note</th>
                <th scope="col"><span class="sr-only">Actions</span></th>
              </tr></thead>
              <tbody>
                @for (t of v.transactions; track t.id) {
                  <tr>
                    <td>{{ shortDate(t.trade_date) }}</td>
                    <td><span class="chip" [class.chip-up]="t.side === 'buy'" [class.chip-down]="t.side === 'sell'">{{ t.side === 'buy' ? 'Buy' : 'Sell' }}</span> {{ t.symbol }}</td>
                    <td class="num">{{ qty(t.quantity) }}</td>
                    <td class="num">{{ price(t.price) }}</td>
                    <td class="num">{{ money(t.quantity * t.price + (t.side === 'buy' ? t.fees : -t.fees)) }}</td>
                    <td class="small muted">{{ t.note }}</td>
                    <td>
                      @if (confirming() === t.id) {
                        <button class="btn btn-quiet down" type="button" (click)="remove(t.id)">Confirm removal</button>
                        <button class="btn btn-quiet" type="button" (click)="confirming.set(null)">Keep</button>
                      } @else {
                        <button class="btn btn-quiet" type="button" (click)="confirming.set(t.id)"
                                [attr.aria-label]="'Remove the ' + t.side + ' of ' + t.symbol + ' on ' + shortDate(t.trade_date)">Remove</button>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      }
    }
  `,
  styles: `
    .intro { padding-top: 2rem; }
    .intro p { margin-top: 0.5rem; max-width: 60rem; }
    .range-value { font-size: var(--step-1); }
    .warnings { list-style: none; margin: 0 0 0.75rem; padding: 0; display: grid; gap: 0.5rem; }
    .warning { display: flex; gap: 0.75rem; align-items: flex-start; padding: 0.7rem 0.9rem; border-radius: var(--radius-m);
      background: var(--paper-raised); border: 1px solid var(--grid); max-width: 60rem; }
    .badge-level { flex: none; display: grid; place-items: center; width: 1.4rem; height: 1.4rem; border-radius: 50%;
      font-weight: 700; font-size: 0.8rem; background: var(--luck); color: var(--ink-soft); }
    .level-high .badge-level { background: var(--down); color: #fff; }
    .level-medium .badge-level { background: var(--down-wash); color: var(--down); }
    .all-clear { padding: 0.7rem 0.9rem; border-radius: var(--radius-m); background: var(--up-wash); color: var(--up);
      font-weight: 600; max-width: 60rem; }
    .asset-link { font-weight: 700; text-decoration: none; color: var(--accent); }
    .name { max-width: 16rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .range { white-space: nowrap; }
    .strong { font-weight: 600; }
    .weight { display: inline-flex; align-items: center; gap: 0.5rem; min-width: 6.5rem; }
    .weight-track { flex: 1; height: 6px; background: var(--grid); border-radius: 3px; overflow: hidden; min-width: 4rem; }
    .weight-fill { display: block; height: 100%; background: var(--accent); }
    .weight.over .weight-fill { background: var(--down); }
    .weight.over .weight-label { color: var(--down); font-weight: 700; }
    .weight-label { font-variant-numeric: tabular-nums; min-width: 2.5rem; text-align: right; }
    .two-col { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 2rem; }
    .sectors { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.5rem; }
    .sectors li { display: grid; grid-template-columns: 9rem 1fr; gap: 0.75rem; align-items: center; font-size: var(--step--1); }
    .trade { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 0.75rem 1rem; align-items: end; max-width: 64rem; }
    .note-field { grid-column: span 3; }
    .submit { display: flex; align-items: end; }
    @media (max-width: 860px) { .two-col { grid-template-columns: 1fr; } .note-field { grid-column: auto; } }
  `,
})
export class PortfolioPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly store = inject(UniverseStores).get(this.universe);
  readonly view = signal<PortfolioView | null>(null);
  readonly error = signal<string | null>(null);
  readonly formError = signal<string | null>(null);
  readonly saved = signal<string | null>(null);
  readonly saving = signal(false);
  readonly confirming = signal<string | null>(null);
  readonly today = new Date().toISOString().slice(0, 10);
  readonly csvUrl = this.api.transactionsCsvUrl(this.universe);

  form: NewTransaction = this.blankForm();

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.portfolio(this.universe).subscribe({
      next: (v) => { this.view.set(v); this.error.set(null); },
      error: (err) => this.error.set(describeError(err)),
    });
  }

  readonly held = computed<Position[]>(() =>
    (this.view()?.positions ?? []).filter((p) => p.quantity > 0).sort((a, b) => b.weight - a.weight));
  readonly closed = computed<Position[]>(() => (this.view()?.positions ?? []).filter((p) => p.quantity <= 0));

  readonly historyChart = computed<ChartConfiguration | null>(() => {
    const v = this.view();
    if (!v || v.history.length < 2) return null;
    const c = themeColors();
    const datasets: ChartConfiguration['data']['datasets'] = [
      { label: 'Your portfolio', data: v.history.map((h) => h.value), borderColor: c.accent, backgroundColor: c.accent },
      { label: 'Money put in', data: v.history.map((h) => h.invested), borderColor: c.faint, backgroundColor: c.faint,
        borderDash: [4, 4], borderWidth: 1.5 },
    ];
    if (v.history.some((h) => h.benchmark != null)) {
      datasets.splice(1, 0, { label: 'Benchmark, same money', data: v.history.map((h) => h.benchmark),
        borderColor: c.soft, backgroundColor: c.soft });
    }
    return {
      type: 'line',
      data: { labels: v.history.map((h) => shortDate(h.date)), datasets },
      options: baseOptions((n) => this.money(n)) as ChartConfiguration['options'],
    };
  });

  /** Fill the price with the latest close when a held or ranked asset is chosen */
  suggestPrice(): void {
    const symbol = (this.form.symbol || '').toUpperCase();
    const held = this.view()?.positions.find((p) => p.symbol === symbol);
    const ranked = this.store.analysis()?.rankings.find((r) => r.symbol === symbol);
    const latest = held?.price ?? ranked?.current_price;
    if (latest && !this.form.price) this.form.price = Math.round(latest * 100) / 100;
  }

  submit(): void {
    this.formError.set(null);
    this.saved.set(null);
    const t = { ...this.form, symbol: (this.form.symbol || '').trim().toUpperCase(), note: this.form.note?.trim() || null };
    if (!t.symbol || !t.quantity || !t.price || !t.trade_date) {
      this.formError.set('Fill in the asset, date, quantity and price.');
      return;
    }
    this.saving.set(true);
    this.api.addTransaction(this.universe, t).subscribe({
      next: (saved) => {
        this.saving.set(false);
        this.saved.set(`Recorded: ${saved.side === 'buy' ? 'bought' : 'sold'} ${this.qty(saved.quantity)} ${saved.symbol} on ${shortDate(saved.trade_date)}.`);
        this.form = this.blankForm();
        this.load();
      },
      error: (err) => { this.saving.set(false); this.formError.set(describeError(err)); },
    });
  }

  remove(id: string): void {
    this.confirming.set(null);
    this.api.deleteTransaction(this.universe, id).subscribe({
      next: () => this.load(),
      error: (err) => this.formError.set(describeError(err)),
    });
  }

  levelName(level: string): string {
    return level === 'high' ? 'Important' : level === 'medium' ? 'Worth a look' : 'For information';
  }

  money(value: number | null | undefined): string {
    if (value == null || Number.isNaN(value)) return '–';
    return value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: Math.abs(value) >= 1000 ? 0 : 2 });
  }

  signedMoney(value: number | null | undefined): string {
    if (value == null || Number.isNaN(value)) return '–';
    return (value > 0 ? '+' : value < 0 ? '−' : '') + this.money(Math.abs(value));
  }

  qty(value: number): string {
    return value.toLocaleString('en-US', { maximumFractionDigits: 6 });
  }

  private blankForm(): NewTransaction {
    // Empty quantity and price fields (rather than 0) until the user types
    return { symbol: '', side: 'buy', trade_date: new Date().toISOString().slice(0, 10),
      quantity: null as unknown as number, price: null as unknown as number, fees: 0, note: null };
  }

  readonly pct = pct;
  readonly price = price;
  readonly shortDate = shortDate;
}
