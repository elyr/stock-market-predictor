import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';

import { ApiService } from './api.service';
import { Analysis, Job, MarketItem, Universe, UniverseInfo } from './models';

/**
 * State for one dashboard (stocks or crypto): its settings, latest analysis,
 * benchmark moves and any running job. Each universe has its own instance, so
 * the two dashboards never share state.
 */
export class UniverseStore {
  readonly info = signal<UniverseInfo | null>(null);
  readonly analysis = signal<Analysis | null>(null);
  readonly market = signal<MarketItem[]>([]);
  readonly job = signal<Job | null>(null);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  readonly running = computed(() => {
    const job = this.job();
    return !!job && (job.status === 'queued' || job.status === 'running');
  });

  constructor(readonly key: Universe, private readonly api: ApiService) {}

  load(): void {
    this.loading.set(true);
    this.api.universe(this.key).subscribe({
      next: (info) => this.info.set(info),
      error: (err) => this.error.set(describeError(err)),
    });
    this.api.market(this.key).subscribe({ next: (m) => this.market.set(m.items), error: () => this.market.set([]) });
    this.refreshAnalysis();
    // Pick up a job started elsewhere (e.g. demo seeding on server start)
    this.api.jobs(this.key).subscribe({
      next: (jobs) => {
        const active = jobs.find((j) => j.status === 'queued' || j.status === 'running');
        if (active) this.follow(active);
      },
    });
  }

  refreshAnalysis(): void {
    this.api.latestAnalysis(this.key).subscribe({
      next: (analysis) => {
        this.analysis.set(analysis);
        this.loading.set(false);
        this.error.set(null);
      },
      error: (err: HttpErrorResponse) => {
        this.loading.set(false);
        if (err.status === 404) this.analysis.set(null);
        else this.error.set(describeError(err));
      },
    });
  }

  runAnalysis(): void {
    this.api.startAnalysis(this.key).subscribe({
      next: (job) => this.follow(job),
      error: (err) => this.error.set(describeError(err)),
    });
  }

  follow(job: Job, onDone?: (job: Job) => void): void {
    this.job.set(job);
    this.api.watchJob(job.id).subscribe({
      next: (update) => {
        this.job.set(update);
        if (update.status === 'succeeded') {
          this.refreshAnalysis();
          this.api.market(this.key).subscribe({ next: (m) => this.market.set(m.items) });
          this.api.universe(this.key).subscribe({ next: (info) => this.info.set(info) });
        }
        if (update.status === 'succeeded' || update.status === 'failed') onDone?.(update);
      },
      error: (err) => this.error.set(describeError(err)),
    });
  }
}

export function describeError(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    if (err.status === 0) return 'The prediction server is not reachable. Start it with: uvicorn api.main:app';
    const detail = (err.error && (err.error as { detail?: string }).detail) || err.message;
    return `${detail}`;
  }
  return String(err);
}

@Injectable({ providedIn: 'root' })
export class UniverseStores {
  private readonly api = inject(ApiService);
  private readonly stores = new Map<Universe, UniverseStore>();

  get(key: Universe): UniverseStore {
    let store = this.stores.get(key);
    if (!store) {
      store = new UniverseStore(key, this.api);
      this.stores.set(key, store);
      store.load();
    }
    return store;
  }
}
