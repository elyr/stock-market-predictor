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
  templateUrl: './alerts.html',
  styleUrl: './alerts.scss',
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
