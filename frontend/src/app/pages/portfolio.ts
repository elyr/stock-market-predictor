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
  templateUrl: './portfolio.html',
  styleUrl: './portfolio.scss',
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
