import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, switchMap, timer } from 'rxjs';

import {
  Analysis, AppNotification, AssetDetail, BacktestListItem, BacktestRecord, Experiment, Job, MarketItem,
  PerformanceReport, SettingSpec, SignalSchedule, TrackRecord, Universe, UniverseInfo, UnreadCount, VolatilityView,
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

  notifications(universe: Universe, unreadOnly = false) {
    return this.http.get<AppNotification[]>(`${this.base}/notifications`, {
      params: { universe, unread_only: unreadOnly, limit: 200 },
    });
  }

  unreadCounts() {
    return this.http.get<Record<Universe, UnreadCount>>(`${this.base}/notifications/unread`);
  }

  markRead(id: number) {
    return this.http.post<AppNotification>(`${this.base}/notifications/${id}/read`, {});
  }

  markAllRead(universe: Universe) {
    return this.http.post<{ marked: number }>(`${this.base}/notifications/read-all`, {}, { params: { universe } });
  }

  scanSignals(universe: Universe, session: 'open' | 'close' = 'close') {
    return this.http.post<Job>(`${this.base}/${universe}/signals/scan`, { session });
  }

  signalSchedule() {
    return this.http.get<SignalSchedule>(`${this.base}/signals/schedule`);
  }

  performance(universe: Universe, source: 'live' | 'backtest', backtestId?: string | null) {
    const params: Record<string, string> = { source };
    if (backtestId) params['backtest_id'] = backtestId;
    return this.http.get<PerformanceReport>(`${this.base}/${universe}/performance`, { params });
  }

  predictionsCsvUrl(universe: Universe, source: 'live' | 'backtest', backtestId?: string | null): string {
    const query = new URLSearchParams({ source });
    if (backtestId) query.set('backtest_id', backtestId);
    return `${this.base}/${universe}/performance/predictions.csv?${query}`;
  }

  experimentSettings() {
    return this.http.get<Record<string, SettingSpec>>(`${this.base}/experiments/settings`);
  }

  experiments(universe: Universe) {
    return this.http.get<{ lockbox_days: number; test_days: number; experiments: Experiment[] }>(
      `${this.base}/${universe}/experiments`);
  }

  createExperiment(universe: Universe, body: { name: string; settings: Record<string, unknown>; top_n?: number | null }) {
    return this.http.post<{ experiment_id: string; job: Job }>(`${this.base}/${universe}/experiments`, body);
  }

  checkLockbox(universe: Universe, id: string) {
    return this.http.post<Job>(`${this.base}/${universe}/experiments/${id}/lockbox`, {});
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

