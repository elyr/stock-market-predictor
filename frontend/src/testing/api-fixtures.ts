import { HttpTestingController } from '@angular/common/http/testing';

import cryptoAnalysis from './fixtures/crypto_analysis_latest.json';
import cryptoAsset from './fixtures/crypto_asset.json';
import cryptoBacktests from './fixtures/crypto_backtests.json';
import cryptoForecast from './fixtures/crypto_forecast.json';
import cryptoInfo from './fixtures/crypto_info.json';
import cryptoMarket from './fixtures/crypto_market.json';
import cryptoTrack from './fixtures/crypto_track_record.json';
import cryptoVol from './fixtures/crypto_volatility.json';
import stocksAnalysis from './fixtures/stocks_analysis_latest.json';
import stocksAsset from './fixtures/stocks_asset.json';
import stocksBacktestDetail from './fixtures/stocks_backtest_detail.json';
import stocksBacktests from './fixtures/stocks_backtests.json';
import stocksForecast from './fixtures/stocks_forecast.json';
import stocksInfo from './fixtures/stocks_info.json';
import stocksMarket from './fixtures/stocks_market.json';
import stocksModels from './fixtures/stocks_models.json';
import stocksTrack from './fixtures/stocks_track_record.json';
import stocksVol from './fixtures/stocks_volatility.json';
import cryptoNotifications from './fixtures/crypto_notifications.json';
import experimentSettings from './fixtures/experiment_settings.json';
import schedule from './fixtures/schedule.json';
import stocksExperiments from './fixtures/stocks_experiments.json';
import stocksNotifications from './fixtures/stocks_notifications.json';
import stocksPerformance from './fixtures/stocks_performance.json';
import unread from './fixtures/unread.json';

/** Real responses captured from the API running in demo mode. */
export const fixtures = {
  stocks: { info: stocksInfo, analysis: stocksAnalysis, market: stocksMarket, volatility: stocksVol,
    track: stocksTrack, backtests: stocksBacktests, backtest: stocksBacktestDetail, asset: stocksAsset,
    notifications: stocksNotifications, performance: stocksPerformance, experiments: stocksExperiments,
    models: stocksModels, forecast: stocksForecast },
  crypto: { info: cryptoInfo, analysis: cryptoAnalysis, market: cryptoMarket, volatility: cryptoVol,
    track: cryptoTrack, backtests: cryptoBacktests, backtest: null, asset: cryptoAsset,
    notifications: cryptoNotifications, performance: null, experiments: { lockbox_days: 60, test_days: 250, experiments: [] },
    models: { enabled: true, name: 'ledger-crypto-demo', tracking_uri: 'sqlite:///data/mlflow-demo.db', ui_url: null,
      champion: null, pinned: false, versions: [] }, forecast: cryptoForecast },
  unread,
  schedule,
  experimentSettings,
};

type Overrides = Partial<Record<string, unknown>>;

function lookup(url: string, overrides: Overrides): { body: unknown; status: number } {
  const path = url.split('?')[0];
  if (path in overrides) {
    const body = overrides[path];
    return body === undefined ? { body: { detail: 'Not Found' }, status: 404 } : { body, status: 200 };
  }
  if (path === '/api/health') return { body: { status: 'ok', version: 'test', demo: true }, status: 200 };
  if (path === '/api/jobs') return { body: [], status: 200 };
  if (path === '/api/notifications/unread') return { body: fixtures.unread, status: 200 };
  if (path === '/api/signals/schedule') return { body: fixtures.schedule, status: 200 };
  if (path === '/api/experiments/settings') return { body: fixtures.experimentSettings, status: 200 };
  if (path === '/api/notifications') {
    const universe = new URLSearchParams(url.split('?')[1] ?? '').get('universe') as 'stocks' | 'crypto' | null;
    return { body: universe ? fixtures[universe].notifications : [], status: 200 };
  }
  const match = path.match(/^\/api\/(stocks|crypto)(?:\/(.*))?$/);
  if (!match) return { body: { detail: 'Not Found' }, status: 404 };
  const f = fixtures[match[1] as 'stocks' | 'crypto'];
  const rest = match[2] ?? '';
  const table: Record<string, unknown> = {
    '': f.info, 'analysis/latest': f.analysis, 'market': f.market, 'volatility': f.volatility,
    'track-record': f.track, 'backtests': f.backtests, 'experiments': f.experiments, 'models': f.models,
    'forecast': f.forecast,
  };
  if (rest === 'performance') {
    return f.performance ? { body: f.performance, status: 200 } : { body: { detail: 'Not Found' }, status: 404 };
  }
  if (rest in table) return { body: table[rest], status: 200 };
  if (rest.startsWith('backtests/') && f.backtest) return { body: f.backtest, status: 200 };
  if (rest.startsWith('assets/')) return { body: f.asset, status: 200 };
  return { body: { detail: 'Not Found' }, status: 404 };
}

/** Answer every pending request (and the ones they trigger) from the fixtures. */
export function respondAll(http: HttpTestingController, overrides: Overrides = {}): string[] {
  const seen: string[] = [];
  for (let round = 0; round < 10; round++) {
    const pending = http.match(() => true);
    if (!pending.length) break;
    for (const req of pending) {
      seen.push(`${req.request.method} ${req.request.urlWithParams}`);
      const { body, status } = lookup(req.request.urlWithParams, overrides);
      if (status === 200) req.flush(body as object | null);
      else req.flush(body as object, { status, statusText: 'Not Found' });
    }
  }
  return seen;
}
