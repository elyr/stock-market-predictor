import { TestBed } from '@angular/core/testing';

import { fixtures } from '../../testing/api-fixtures';
import { renderRoute, text } from '../../testing/setup';

describe('Stocks outlook', () => {
  it('shows the evidence verdict, the portfolio and the model facts', async () => {
    const { root } = await renderRoute('/stocks');
    const page = text(root);
    expect(page).toContain('US Stocks');
    expect(page).toContain('Is the model better than luck?');
    expect(page).toMatch(/Indistinguishable from luck|evidence of skill|Consistently wrong/);
    const picks = root.querySelectorAll('table.picks tbody tr');
    expect(picks.length).toBe(fixtures.stocks.analysis.picks.length);
    expect(text(picks[0])).toContain(fixtures.stocks.analysis.picks[0].symbol);
    expect(page).toContain('How the model is built and checked');
  });

  it('reveals the reasons for a pick', async () => {
    const { root, harness } = await renderRoute('/stocks');
    const why = root.querySelector('table.picks button.btn-quiet') as HTMLButtonElement;
    why.click();
    harness.detectChanges();
    const detail = text(root.querySelector('.detail-row'));
    expect(detail).toContain('What the model weighed');
    expect(detail).toContain(fixtures.stocks.analysis.picks[0].explanation[0].label);
    expect(why.getAttribute('aria-expanded')).toBe('true');
  });

  it('invites a first run when there is no analysis yet', async () => {
    const { root } = await renderRoute('/stocks', { '/api/stocks/analysis/latest': undefined });
    expect(text(root)).toContain('No outlook yet');
  });
});

describe('Crypto outlook', () => {
  it('is a separate dashboard with its own data and accent', async () => {
    const { root } = await renderRoute('/crypto');
    expect(text(root)).toContain('Crypto');
    expect(text(root)).toContain('coins');
    expect(root.querySelector('app-universe-layout')?.className).toContain('theme-crypto');
    const symbols = Array.from(root.querySelectorAll('table.picks .asset-link')).map((a) => a.textContent?.trim());
    expect(symbols.every((s) => s?.endsWith('-USD'))).toBe(true);
    expect(text(root)).toContain('Bitcoin');
  });
});

describe('Backtest page', () => {
  it('loads the latest backtest with a verdict, metrics and IC table', async () => {
    const { root } = await renderRoute('/stocks/backtest');
    const page = text(root);
    expect(page).toContain('What if you had followed these picks?');
    expect(page).toContain('After costs the picks returned');
    expect(root.querySelectorAll('table.data')[0].querySelectorAll('tbody tr').length)
      .toBe(fixtures.stocks.backtest.result.metrics.length);
    expect(page).toContain('Does the score rank assets in the right order?');
  });

  it('shows an empty state when no backtest exists', async () => {
    const { root } = await renderRoute('/crypto/backtest', { '/api/crypto/backtests': [] });
    expect(text(root)).toContain('No backtests yet');
  });
});

describe('Track record page', () => {
  it('separates the live record from simulated demo history', async () => {
    const { root } = await renderRoute('/stocks/track-record');
    const page = text(root);
    expect(page).toContain('Every prediction, scored after the fact');
    expect(page).toContain('Live record');
    expect(page).toContain('Simulated history');
    expect(page).toContain('Not real predictions');
    expect(page).toMatch(/waiting for 5 days of prices|Periods scored/);
  });
});

describe('Volatility page', () => {
  it('lists every asset with its forecast and the model skill against the naive guess', async () => {
    const { root } = await renderRoute('/crypto/volatility');
    expect(text(root)).toContain('Which way is the turbulence heading?');
    expect(root.querySelectorAll('tbody tr').length).toBe(fixtures.crypto.volatility.assets.length);
    expect(text(root)).toContain('for assuming it stays the same');
  });
});

describe('Models page', () => {
  it('lists versions with their scores, marks the pinned champion and offers a roll back', async () => {
    const { root } = await renderRoute('/stocks/models');
    const page = text(root);
    expect(page).toContain('Model versions');
    expect(page).toContain('Pinned to version 2');
    expect(page).toContain('Resume retraining');
    const rows = root.querySelectorAll('tbody tr');
    expect(rows.length).toBe(3);
    expect(text(rows[1])).toContain('Champion');
    expect(text(rows[1])).toContain('Some evidence of skill');
    expect(text(rows[2])).toContain('Roll back to this');
    expect(root.querySelector('a[href="http://mlflow.localhost:8080"]')).not.toBeNull();
  });

  it('invites a first analysis when nothing is registered yet', async () => {
    const { root } = await renderRoute('/crypto/models');
    expect(text(root)).toContain('No versions yet');
    expect(root.querySelectorAll('tbody tr').length).toBe(0);
  });
});

describe('Asset page', () => {
  it('shows price, standing and reasons for one asset', async () => {
    const { root } = await renderRoute('/crypto/asset/BTC-USD');
    const page = text(root);
    expect(page).toContain('BTC-USD');
    expect(page).toContain('Rank in the latest analysis');
    expect(page).toContain('Why it ranks where it does');
  });
});

describe('Navigation', () => {
  it('offers both dashboards with the same sections', async () => {
    const { App } = await import('../app');
    TestBed.resetTestingModule();
    await renderRoute('/stocks');
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const nav = text(fixture.nativeElement.querySelector('nav'));
    for (const label of ['US Stocks', 'Crypto', 'Outlook', 'Backtest', 'Track record', 'Models', 'Volatility']) {
      expect(nav).toContain(label);
    }
  });
});
