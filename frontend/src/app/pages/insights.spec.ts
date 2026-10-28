import { TestBed } from '@angular/core/testing';

import { fixtures } from '../../testing/api-fixtures';
import { renderRoute, text } from '../../testing/setup';

describe('Alerts page', () => {
  it('lists alerts by day with severity, kind and a link to the asset', async () => {
    const { root } = await renderRoute('/stocks/alerts');
    const page = text(root);
    expect(page).toContain('Unusual moves, checked twice a day');
    expect(page).toContain('09:45');
    expect(page).toContain('16:15');
    const items = root.querySelectorAll('li.alert');
    expect(items.length).toBe(fixtures.stocks.notifications.length);
    expect(text(items[0])).toMatch(/Critical|Notable|For information/);
    const withSymbol = fixtures.stocks.notifications.find((n) => n.symbol);
    if (withSymbol) expect(page).toContain(`Open ${withSymbol.symbol}`);
  });

  it('filters to unread and shows the unread count', async () => {
    const { root, harness } = await renderRoute('/stocks/alerts');
    const unreadButton = Array.from(root.querySelectorAll('.chip-toggle')).find((b) => b.textContent?.includes('Unread')) as HTMLButtonElement;
    expect(unreadButton.textContent).toContain(`(${fixtures.stocks.notifications.filter((n) => !n.read).length})`);
    unreadButton.click();
    harness.detectChanges();
    expect(unreadButton.getAttribute('aria-pressed')).toBe('true');
  });

  it('shows an empty state when there are no alerts', async () => {
    const { root } = await renderRoute('/crypto/alerts', { '/api/notifications': [] });
    expect(text(root)).toContain('No alerts yet');
  });
});

describe('Navigation badges', () => {
  it('shows unread alert counts per dashboard', async () => {
    const { App } = await import('../app');
    await renderRoute('/stocks');
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const { HttpTestingController } = await import('@angular/common/http/testing');
    const { respondAll } = await import('../../testing/api-fixtures');
    respondAll(TestBed.inject(HttpTestingController));
    fixture.detectChanges();
    const badges = Array.from(fixture.nativeElement.querySelectorAll('.badge')).map((b) => (b as Element).textContent?.trim());
    expect(badges).toContain(String(fixtures.unread.stocks.total));
    expect(text(fixture.nativeElement.querySelector('nav'))).toContain('Predicted vs actual');
  });
});

describe('Predicted vs actual page', () => {
  it('shows the verdict, deciles, components, breakdowns and the prediction log', async () => {
    const { root } = await renderRoute('/stocks/performance');
    const page = text(root);
    const report = fixtures.stocks.performance;
    expect(page).toContain('How did the predictions turn out?');
    expect(page).toMatch(/Indistinguishable from luck|evidence of skill|Consistently wrong/);
    expect(page).toContain('Did higher scores do better?');
    expect(page).toContain('Which parts of the score carry signal?');
    expect(page).toContain('By market direction');
    const select = root.querySelector('.source-bar select') as HTMLSelectElement;
    expect(select.options.length).toBe(report.sources.length);
    const csv = root.querySelector('a[download]') as HTMLAnchorElement;
    expect(csv.getAttribute('href')).toContain('/api/stocks/performance/predictions.csv');
    expect(root.querySelectorAll('table.data').length).toBeGreaterThanOrEqual(3);
    expect(text(root)).toContain(report.log[0].symbol);
  });

  it('explains what to do when there is nothing to compare', async () => {
    const { root } = await renderRoute('/crypto/performance');
    expect(text(root)).toContain('Nothing to compare yet');
    expect(text(root)).toContain('Run a backtest');
  });
});

describe('Experiments page', () => {
  it('compares experiments with the baseline and shows locked-period results', async () => {
    const { root } = await renderRoute('/stocks/experiments');
    const page = text(root);
    expect(page).toContain('Experiments');
    expect(page).toContain('Development period');
    expect(page).toContain('Baseline');
    const rows = root.querySelectorAll('tbody tr');
    expect(rows.length).toBe(fixtures.stocks.experiments.experiments.length);
    const checked = fixtures.stocks.experiments.experiments.find((e) => e.lockbox);
    if (checked) expect(page).toMatch(/Held up|Weakened|Did not hold up/);
    const unchecked = fixtures.stocks.experiments.experiments.find((e) => !e.lockbox);
    if (unchecked) expect(page).toContain('Check on locked period');
  });

  it('offers the main settings in the form', async () => {
    const { root } = await renderRoute('/stocks/experiments');
    const labels = text(root.querySelector('form.exp-form'));
    for (const label of ['Weight: momentum', 'Prediction horizon', 'XGBoost depth', 'Position sizing', 'Picks per period']) {
      expect(labels).toContain(label);
    }
  });

  it('suggests measuring the current settings first when nothing has run', async () => {
    const { root } = await renderRoute('/crypto/experiments');
    expect(text(root)).toContain('Measure the current settings first');
  });
});
