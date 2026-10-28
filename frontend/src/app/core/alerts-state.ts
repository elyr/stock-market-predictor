import { Injectable, OnDestroy, inject, signal } from '@angular/core';

import { ApiService } from './api.service';
import { Universe, UnreadCount } from './models';

const EMPTY: UnreadCount = { total: 0, critical: 0, warning: 0, info: 0 };

/** Unread alert counts for both dashboards, refreshed every minute. */
@Injectable({ providedIn: 'root' })
export class AlertsState implements OnDestroy {
  private readonly api = inject(ApiService);
  private timer?: ReturnType<typeof setInterval>;
  readonly counts = signal<Record<Universe, UnreadCount>>({ stocks: EMPTY, crypto: EMPTY });

  start(intervalMs = 60_000): void {
    this.refresh();
    if (!this.timer && typeof window !== 'undefined') {
      this.timer = setInterval(() => this.refresh(), intervalMs);
    }
  }

  refresh(): void {
    this.api.unreadCounts().subscribe({ next: (counts) => this.counts.set(counts), error: () => undefined });
  }

  count(universe: Universe): UnreadCount {
    return this.counts()[universe] ?? EMPTY;
  }

  ngOnDestroy(): void {
    if (this.timer) clearInterval(this.timer);
  }
}
