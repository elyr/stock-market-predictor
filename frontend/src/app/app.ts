import { Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AlertsState } from './core/alerts-state';
import { ApiService } from './core/api.service';
import { Universe } from './core/models';

interface NavSection { path: string; label: string; exact?: boolean; badge?: boolean }
interface NavGroup { label: string; sections: NavSection[] }

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
  /** Pages grouped by the question they answer. */
  readonly groups: NavGroup[] = [
    { label: 'Today', sections: [
      { path: '', label: 'Outlook', exact: true },
      { path: 'forecast', label: 'Forecast' },
      { path: 'volatility', label: 'Volatility' },
      { path: 'alerts', label: 'Alerts', badge: true },
    ] },
    { label: 'Is it working?', sections: [
      { path: 'track-record', label: 'Track record' },
      { path: 'backtest', label: 'Backtest' },
      { path: 'performance', label: 'Predicted vs actual' },
    ] },
    { label: 'Improve it', sections: [
      { path: 'experiments', label: 'Experiments' },
      { path: 'models', label: 'Models' },
    ] },
  ];
  readonly alerts = inject(AlertsState);

  constructor() {
    this.api.health().subscribe({ next: (h) => this.demo.set(h.demo), error: () => this.demo.set(false) });
    this.alerts.start();
  }
}
