import { Routes } from '@angular/router';

import { UniverseLayout } from './pages/universe-layout';

const sections: Routes = [
  { path: '', loadComponent: () => import('./pages/outlook').then((m) => m.OutlookPage), title: 'Outlook' },
  { path: 'backtest', loadComponent: () => import('./pages/backtest').then((m) => m.BacktestPage), title: 'Backtest' },
  { path: 'track-record', loadComponent: () => import('./pages/track-record').then((m) => m.TrackRecordPage), title: 'Track record' },
  { path: 'alerts', loadComponent: () => import('./pages/alerts').then((m) => m.AlertsPage), title: 'Alerts' },
  { path: 'volatility', loadComponent: () => import('./pages/volatility').then((m) => m.VolatilityPage), title: 'Volatility' },
  { path: 'asset/:symbol', loadComponent: () => import('./pages/asset').then((m) => m.AssetPage), title: 'Asset' },
];

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'stocks' },
  { path: 'stocks', component: UniverseLayout, data: { universe: 'stocks' }, children: sections },
  { path: 'crypto', component: UniverseLayout, data: { universe: 'crypto' }, children: sections },
  { path: '**', redirectTo: 'stocks' },
];
