import { Component, OnInit, computed, inject, signal } from '@angular/core';

import { ApiService } from '../core/api.service';
import { evidence, num, shortDate } from '../core/format';
import { ModelRegistryView, ModelVersion } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { UniverseStores, describeError } from '../core/universe-store';
import { HintComponent } from '../shared/hint';

@Component({
  selector: 'app-models',
  imports: [HintComponent],
  templateUrl: './models.html',
  styleUrl: './models.scss',
})
export class ModelsPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly store = inject(UniverseStores).get(this.universe);
  readonly view = signal<ModelRegistryView | null>(null);
  readonly error = signal<string | null>(null);
  readonly message = signal<string | null>(null);
  readonly busy = signal(false);
  private readonly championNumber = computed(() => Number(this.view()?.champion ?? 0));

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.models(this.universe).subscribe({
      next: (v) => this.view.set(v),
      error: (err) => this.error.set(describeError(err)),
    });
  }

  promote(m: ModelVersion): void {
    this.change(this.api.promoteModel(this.universe, m.version),
      `Version ${m.version} is now the champion and pinned. The next analysis uses it without retraining.`);
  }

  unpin(): void {
    this.change(this.api.unpinModel(this.universe),
      'Retraining resumed. The next analysis trains new models and saves them as a new version.');
  }

  private change(request: ReturnType<ApiService['models']>, done: string): void {
    this.busy.set(true);
    this.error.set(null);
    request.subscribe({
      next: (v) => { this.view.set(v); this.message.set(done); this.busy.set(false); },
      error: (err) => { this.error.set(describeError(err)); this.busy.set(false); },
    });
  }

  metric(m: ModelVersion, key: string): number | null {
    const value = m.metrics[key];
    return value == null || Number.isNaN(value) ? null : value;
  }

  ic(m: ModelVersion): number {
    return this.metric(m, 'quality.ic_mean') ?? 0;
  }

  verdict(m: ModelVersion): string {
    return evidence(this.metric(m, 'quality.ic_t_stat')).label;
  }

  isOlder(m: ModelVersion): boolean {
    return Number(m.version) < this.championNumber();
  }

  readonly num = num;
  readonly shortDate = shortDate;
}
