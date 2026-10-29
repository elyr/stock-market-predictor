import { Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AlertsState } from './core/alerts-state';
import { ApiService } from './core/api.service';
import { Universe } from './core/models';

interface NavSection { path: string; label: string; exact?: boolean; badge?: boolean }

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private readonly api = inject(ApiService);
  readonly demo = signal(false);
  readonly menuOpen = signal(false);

  readonly dashboards: { key: Universe; label: string }[] = [
    { key: 'stocks', label: 'US Stocks' },
    { key: 'crypto', label: 'Crypto' },
  ];
  readonly sections: NavSection[] = [
    { path: '', label: 'Outlook', exact: true },
    { path: 'backtest', label: 'Backtest' },
    { path: 'track-record', label: 'Track record' },
    { path: 'performance', label: 'Predicted vs actual' },
    { path: 'experiments', label: 'Experiments' },
    { path: 'models', label: 'Models' },
    { path: 'volatility', label: 'Volatility' },
    { path: 'alerts', label: 'Alerts', badge: true },
  ];
  readonly alerts = inject(AlertsState);

  constructor() {
    this.api.health().subscribe({ next: (h) => this.demo.set(h.demo), error: () => this.demo.set(false) });
    this.alerts.start();
  }
}
