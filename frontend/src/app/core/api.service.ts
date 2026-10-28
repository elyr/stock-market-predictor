import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, switchMap, timer } from 'rxjs';

import {
  Analysis, AssetDetail, BacktestListItem, BacktestRecord, Job, MarketItem, TrackRecord,
  Universe, UniverseInfo, VolatilityView,
} from './models';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api';

  health() {
    return this.http.get<{ status: string; version: string; demo: boolean }>(`${this.base}/health`);
  }

  universe(universe: Universe) {
    return this.http.get<UniverseInfo>(`${this.base}/${universe}`);
  }

  latestAnalysis(universe: Universe) {
    return this.http.get<Analysis>(`${this.base}/${universe}/analysis/latest`);
  }

  startAnalysis(universe: Universe, topN?: number) {
    return this.http.post<Job>(`${this.base}/${universe}/analysis`, { top_n: topN ?? null });
  }

  asset(universe: Universe, symbol: string) {
    return this.http.get<AssetDetail>(`${this.base}/${universe}/assets/${encodeURIComponent(symbol)}`);
  }

  volatility(universe: Universe) {
    return this.http.get<VolatilityView>(`${this.base}/${universe}/volatility`);
  }

  market(universe: Universe) {
    return this.http.get<{ items: MarketItem[] }>(`${this.base}/${universe}/market`);
  }

  trackRecord(universe: Universe) {
    return this.http.get<TrackRecord>(`${this.base}/${universe}/track-record`);
  }

  evaluateOutcomes(universe: Universe) {
    return this.http.post<Job>(`${this.base}/${universe}/track-record/evaluate`, {});
  }

  backtests(universe: Universe) {
    return this.http.get<BacktestListItem[]>(`${this.base}/${universe}/backtests`);
  }

  backtest(universe: Universe, id: string) {
    return this.http.get<BacktestRecord>(`${this.base}/${universe}/backtests/${id}`);
  }

  startBacktest(universe: Universe, params: { top_n?: number; test_days?: number; cost_bps?: number; use_ml?: boolean }) {
    return this.http.post<Job>(`${this.base}/${universe}/backtests`, params);
  }

  jobs(universe: Universe) {
    return this.http.get<Job[]>(`${this.base}/jobs`, { params: { universe } });
  }

  job(id: string) {
    return this.http.get<Job>(`${this.base}/jobs/${id}`);
  }

  /** Poll a job every `intervalMs` until it succeeds or fails; emits each update. */
  watchJob(id: string, intervalMs = 1500): Observable<Job> {
    return timer(0, intervalMs).pipe(
      switchMap(() => this.job(id)),
      takeUntilDone(),
    );
  }
}

/** Emit job updates up to and including the first finished one. */
function takeUntilDone() {
  return (source: Observable<Job>) =>
    new Observable<Job>((subscriber) =>
      source.subscribe({
        next: (job) => {
          subscriber.next(job);
          if (job.status === 'succeeded' || job.status === 'failed') {
            subscriber.complete();
          }
        },
        error: (err) => subscriber.error(err),
        complete: () => subscriber.complete(),
      }),
    );
}

