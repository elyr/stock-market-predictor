import { Routes } from '@angular/router';

import { UniverseLayout } from './pages/universe-layout';

const sections: Routes = [
  { path: '', loadComponent: () => import('./pages/outlook').then((m) => m.OutlookPage), title: 'Outlook' },
  { path: 'brief', loadComponent: () => import('./pages/brief').then((m) => m.BriefPage), title: 'Weekly brief' },
  { path: 'long-term', loadComponent: () => import('./pages/long-term').then((m) => m.LongTermPage), title: 'Long-term' },
  { path: 'portfolio', loadComponent: () => import('./pages/portfolio').then((m) => m.PortfolioPage), title: 'My portfolio' },
  { path: 'next-3-days', loadComponent: () => import('./pages/next-days').then((m) => m.NextDaysPage), title: 'Next 3 days' },
  { path: 'forecast', loadComponent: () => import('./pages/forecast').then((m) => m.ForecastPage), title: 'Forecast' },
  { path: 'backtest', loadComponent: () => import('./pages/backtest').then((m) => m.BacktestPage), title: 'Backtest' },
  { path: 'track-record', loadComponent: () => import('./pages/track-record').then((m) => m.TrackRecordPage), title: 'Track record' },
  { path: 'performance', loadComponent: () => import('./pages/performance').then((m) => m.PerformancePage), title: 'Performance' },
  { path: 'experiments', loadComponent: () => import('./pages/experiments').then((m) => m.ExperimentsPage), title: 'Experiments' },
  { path: 'alerts', loadComponent: () => import('./pages/alerts').then((m) => m.AlertsPage), title: 'Alerts' },
  { path: 'models', loadComponent: () => import('./pages/models').then((m) => m.ModelsPage), title: 'Models' },
  { path: 'volatility', loadComponent: () => import('./pages/volatility').then((m) => m.VolatilityPage), title: 'Volatility' },
  { path: 'asset/:symbol', loadComponent: () => import('./pages/asset').then((m) => m.AssetPage), title: 'Asset' },
];

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'stocks' },
  { path: 'stocks', component: UniverseLayout, data: { universe: 'stocks' }, children: sections },
  { path: 'crypto', component: UniverseLayout, data: { universe: 'crypto' }, children: sections },
  { path: '**', redirectTo: 'stocks' },
];
