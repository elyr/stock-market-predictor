import { Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { ApiService } from './core/api.service';

interface NavSection { path: string; label: string; exact?: boolean }

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

  readonly dashboards = [
    { key: 'stocks', label: 'US Stocks' },
    { key: 'crypto', label: 'Crypto' },
  ];
  readonly sections: NavSection[] = [
    { path: '', label: 'Outlook', exact: true },
    { path: 'backtest', label: 'Backtest' },
    { path: 'track-record', label: 'Track record' },
    { path: 'volatility', label: 'Volatility' },
  ];

  constructor() {
    this.api.health().subscribe({ next: (h) => this.demo.set(h.demo), error: () => this.demo.set(false) });
  }
}
