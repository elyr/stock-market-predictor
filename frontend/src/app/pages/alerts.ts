import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AlertsState } from '../core/alerts-state';
import { ApiService } from '../core/api.service';
import { shortDate } from '../core/format';
import { AppNotification, SignalSchedule } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { describeError } from '../core/universe-store';

const TYPE_LABELS: Record<AppNotification['type'], string> = {
  unusual_move: 'Unusual move',
  volume_spike: 'Volume spike',
  gap: 'Opening gap',
  market_move: 'Market-wide move',
  portfolio_change: 'Portfolio change',
  volatility_rising: 'Volatility rising',
};

const SEVERITY_LABELS = { critical: 'Critical', warning: 'Notable', info: 'For information' };

const SESSION_LABELS: Record<string, string> = {
  open: 'found after the open',
  close: 'found after the close',
  analysis: 'from the latest analysis',
};

@Component({
  selector: 'app-alerts',
  imports: [RouterLink],
  template: `
    <section class="section intro">
      <div class="section-head">
        <div>
          <h2>Unusual moves, checked twice a day</h2>
          <p class="muted">
            Every {{ universe === 'crypto' ? 'day' : 'weekday' }} at {{ schedule()?.open ?? '09:45' }} and
            {{ schedule()?.close ?? '16:15' }} New York time, just after the US market opens and closes, each
            {{ universe === 'crypto' ? 'coin' : 'stock' }} is compared with its own recent history. Alerts flag what
            is unusual, not what will happen next.
          </p>
          @if (nextScan(); as next) {
            <p class="small faint next">Next check {{ next }}.</p>
          }
        </div>
        <div class="actions">
          <button class="btn" type="button" (click)="scan()" [disabled]="scanning()">
            @if (scanning()) { <span class="spinner" aria-hidden="true"></span> Checking } @else { Check now }
          </button>
          <button class="btn btn-quiet" type="button" (click)="markAll()" [disabled]="!unreadCount()">Mark all as read</button>
        </div>
      </div>
      @if (message(); as m) { <p class="small muted" aria-live="polite">{{ m }}</p> }
      @if (error(); as e) { <p class="notice error" role="alert">{{ e }}</p> }

      <div class="filters" role="group" aria-label="Filter alerts">
        <button type="button" class="chip-toggle" [class.on]="!unreadOnly()" (click)="unreadOnly.set(false)" [attr.aria-pressed]="!unreadOnly()">All</button>
        <button type="button" class="chip-toggle" [class.on]="unreadOnly()" (click)="unreadOnly.set(true)" [attr.aria-pressed]="unreadOnly()">Unread ({{ unreadCount() }})</button>
        <label class="type-filter">
          <span class="sr-only">Alert type</span>
          <select [value]="typeFilter()" (change)="typeFilter.set($any($event.target).value)">
            <option value="">Every kind</option>
            @for (t of typeOptions; track t.key) { <option [value]="t.key">{{ t.label }}</option> }
          </select>
        </label>
      </div>
    </section>

    @if (loading()) {
      <p class="muted"><span class="spinner" aria-hidden="true"></span> Loading alerts</p>
    } @else if (!groups().length) {
      <section class="empty">
        <h2>{{ unreadOnly() || typeFilter() ? 'Nothing matches this filter' : 'No alerts yet' }}</h2>
        <p>
          @if (unreadOnly() || typeFilter()) {
            Clear the filter to see every alert.
          } @else {
            Nothing unusual has been found so far. The next scheduled check will run on its own, or run one now.
          }
        </p>
      </section>
    } @else {
      @for (group of groups(); track group.date) {
        <section class="day">
          <h3>{{ shortDate(group.date) }}</h3>
          <ul class="alerts">
            @for (alert of group.items; track alert.id) {
              <li class="alert" [class]="'alert sev-' + alert.severity" [class.unread]="!alert.read">
                <div class="alert-main">
                  <p class="alert-meta small">
                    <span class="sev">{{ severityLabel(alert) }}</span>
                    <span class="faint">{{ typeLabel(alert) }}, {{ sessionLabel(alert) }}</span>
                  </p>
                  <h4>
                    @if (!alert.read) { <span class="dot" aria-label="Unread"></span> }
                    {{ alert.title }}
                  </h4>
                  <p class="body">{{ alert.body }}</p>
                </div>
                <div class="alert-actions">
                  @if (alert.symbol) {
                    <a class="btn btn-quiet" [routerLink]="['../asset', alert.symbol]">Open {{ alert.symbol }}</a>
                  }
                  @if (!alert.read) {
                    <button class="btn btn-quiet" type="button" (click)="markRead(alert)">Mark as read</button>
                  }
                </div>
              </li>
            }
          </ul>
        </section>
      }
    }
  `,
  styles: `
    .intro { padding-top: 2rem; }
    .intro p { margin-top: 0.5rem; }
    .next { margin-top: 0.4rem; }
    .actions { display: flex; gap: 0.5rem; align-items: center; }
    .filters { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; margin-top: 1.25rem; }
    .chip-toggle { font: inherit; font-size: var(--step--1); font-weight: 600; border: 1px solid var(--grid-strong);
      background: var(--paper-raised); color: var(--ink-soft); padding: 0.3rem 0.8rem; border-radius: 999px; cursor: pointer; }
    .chip-toggle.on { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
    .type-filter select { font: inherit; font-size: var(--step--1); padding: 0.3rem 0.5rem; border-radius: var(--radius-m);
      border: 1px solid var(--grid-strong); background: var(--paper-raised); color: var(--ink); }
    .day { padding-top: 1.5rem; }
    .day h3 { font-size: var(--step-0); color: var(--ink-soft); padding-bottom: 0.5rem; border-bottom: 1px solid var(--grid); }
    .alerts { list-style: none; margin: 0; padding: 0; }
    .alert { display: flex; gap: 1.5rem; justify-content: space-between; padding: 1rem 0 1rem 1rem;
      border-bottom: 1px solid var(--grid); border-left: 3px solid var(--grid-strong); }
    .alert.sev-critical { border-left-color: var(--down); }
    .alert.sev-warning { border-left-color: var(--ink); }
    .alert.sev-info { border-left-color: var(--accent); }
    .alert:not(.unread) h4, .alert:not(.unread) .body { color: var(--ink-soft); }
    .alert-meta { display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 0.2rem; }
    .sev { font-weight: 700; }
    .sev-critical .sev { color: var(--down); }
    .sev-info .sev { color: var(--accent); }
    h4 { font-size: var(--step-1); margin: 0 0 0.3rem; display: flex; align-items: center; gap: 0.5rem; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); flex: none; }
    .body { font-size: var(--step--1); }
    .alert-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 0.25rem; flex: none; }
    @media (max-width: 700px) { .alert { flex-direction: column; gap: 0.5rem; } .alert-actions { flex-direction: row; } }
  `,
})
export class AlertsPage implements OnInit {
  private readonly api = inject(ApiService);
  private readonly alertsState = inject(AlertsState);
  readonly universe = injectUniverse();

  readonly alerts = signal<AppNotification[]>([]);
  readonly schedule = signal<SignalSchedule | null>(null);
  readonly loading = signal(true);
  readonly scanning = signal(false);
  readonly message = signal('');
  readonly error = signal<string | null>(null);
  readonly unreadOnly = signal(false);
  readonly typeFilter = signal('');

  readonly typeOptions = Object.entries(TYPE_LABELS).map(([key, label]) => ({ key, label }));
  readonly unreadCount = computed(() => this.alerts().filter((a) => !a.read).length);

  readonly groups = computed(() => {
    const visible = this.alerts().filter((a) =>
      (!this.unreadOnly() || !a.read) && (!this.typeFilter() || a.type === this.typeFilter()));
    const byDate = new Map<string, AppNotification[]>();
    for (const alert of visible) {
      byDate.set(alert.event_date, [...(byDate.get(alert.event_date) ?? []), alert]);
    }
    const rank = { critical: 0, warning: 1, info: 2 };
    return [...byDate.entries()]
      .sort(([a], [b]) => b.localeCompare(a))
      .map(([date, items]) => ({ date, items: items.sort((x, y) => rank[x.severity] - rank[y.severity]) }));
  });

  readonly nextScan = computed(() => {
    const next = this.schedule()?.next?.[this.universe]?.[0];
    if (!next) return '';
    const when = new Date(next.at);
    const label = when.toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' });
    return `${label} your time, ${next.session === 'open' ? 'after the open' : 'after the close'}`;
  });

  ngOnInit(): void {
    this.load();
    this.api.signalSchedule().subscribe({ next: (s) => this.schedule.set(s), error: () => undefined });
  }

  load(): void {
    this.api.notifications(this.universe).subscribe({
      next: (alerts) => {
        this.alerts.set(alerts);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(describeError(err));
      },
    });
  }

  scan(): void {
    this.scanning.set(true);
    this.message.set('');
    this.api.scanSignals(this.universe).subscribe({
      next: (job) => this.api.watchJob(job.id).subscribe((update) => {
        if (update.status === 'succeeded') {
          const created = (update.result as { new_alerts?: number } | null)?.new_alerts ?? 0;
          this.message.set(created ? `${created} new ${created === 1 ? 'alert' : 'alerts'}.` : 'Nothing new since the last check.');
          this.scanning.set(false);
          this.load();
          this.alertsState.refresh();
        } else if (update.status === 'failed') {
          this.scanning.set(false);
          this.error.set(update.error ?? 'The check failed.');
        }
      }),
      error: (err) => {
        this.scanning.set(false);
        this.error.set(describeError(err));
      },
    });
  }

  markRead(alert: AppNotification): void {
    this.api.markRead(alert.id).subscribe(() => {
      this.alerts.update((list) => list.map((a) => (a.id === alert.id ? { ...a, read: true } : a)));
      this.alertsState.refresh();
    });
  }

  markAll(): void {
    this.api.markAllRead(this.universe).subscribe(() => {
      this.alerts.update((list) => list.map((a) => ({ ...a, read: true })));
      this.alertsState.refresh();
    });
  }

  typeLabel(alert: AppNotification): string {
    return TYPE_LABELS[alert.type] ?? alert.type;
  }

  severityLabel(alert: AppNotification): string {
    return SEVERITY_LABELS[alert.severity];
  }

  sessionLabel(alert: AppNotification): string {
    return SESSION_LABELS[alert.session ?? ''] ?? 'found by a check';
  }

  readonly shortDate = shortDate;
}
