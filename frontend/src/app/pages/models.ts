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
  template: `
    <section class="section intro">
      <h2>Model versions</h2>
      <p class="muted">
        Each analysis saves its trained model here as a new version, with the scores it earned on dates it never saw.
        The <strong>champion</strong> <app-hint term="champion" /> is the version in use. If a new version does worse,
        roll back to an earlier one: it is then <strong>pinned</strong> <app-hint term="pinned" /> until you resume retraining.
      </p>
      @if (view()?.ui_url; as ui) {
        <p class="small"><a [href]="ui" target="_blank" rel="noopener">Open MLflow</a> for every run's settings, scores and files.</p>
      }
    </section>

    @if (error(); as e) { <p class="notice error" role="alert">{{ e }}</p> }

    @if (view(); as v) {
      @if (!v.enabled) {
        <section class="empty">
          <h2>The model registry is turned off</h2>
          <p>Models are retrained at every analysis and not kept. Start the server without <code>MODEL_REGISTRY=off</code> to keep every version.</p>
        </section>
      } @else {
        <section class="section">
          <div class="mode" [class.pinned]="v.pinned">
            @if (v.pinned) {
              <div>
                <strong>Pinned to version {{ v.champion }}.</strong>
                Analyses use this version without retraining.
              </div>
              <button class="btn" type="button" (click)="unpin()" [disabled]="busy()">Resume retraining</button>
            } @else if (v.champion) {
              <div><strong>Retraining at every analysis.</strong> Each new version becomes the champion; version {{ v.champion }} is the current one.</div>
            } @else {
              <div><strong>No versions yet.</strong> Run an analysis from the top of the page to train and save the first one.</div>
            }
          </div>
          @if (message(); as m) { <p class="small faint" aria-live="polite">{{ m }}</p> }
        </section>

        @if (v.versions.length) {
          <section class="section">
            <div class="table-wrap">
              <table class="data">
                <thead><tr>
                  <th scope="col">Version</th>
                  <th scope="col">Prices up to</th>
                  <th scope="col">Saved</th>
                  <th scope="col" class="num">Rank IC <app-hint term="ic" /></th>
                  <th scope="col" class="num">t-stat <app-hint term="tStat" /></th>
                  <th scope="col" class="num">AUC <app-hint term="auc" /></th>
                  <th scope="col">Evidence <app-hint term="evidence" /></th>
                  <th scope="col">Code <app-hint term="codeVersion" /></th>
                  <th scope="col"><span class="sr-only">Actions</span></th>
                </tr></thead>
                <tbody>
                  @for (m of v.versions; track m.version) {
                    <tr [class.current]="m.champion">
                      <td>
                        <strong>{{ m.version }}</strong>
                        @if (m.champion) { <span class="chip chip-accent">Champion</span> }
                      </td>
                      <td class="date">{{ shortDate(m.data_date) }}</td>
                      <td class="date faint">{{ shortDate(m.created_at) }}</td>
                      <td class="num" [class.up]="ic(m) > 0" [class.down]="ic(m) < 0">{{ num(metric(m, 'quality.ic_mean'), 3, true) }}</td>
                      <td class="num">{{ num(metric(m, 'quality.ic_t_stat'), 1) }}</td>
                      <td class="num">{{ num(metric(m, 'quality.test_auc'), 3) }}</td>
                      <td>{{ verdict(m) }}</td>
                      <td class="faint mono">{{ m.git_commit ?? '–' }}</td>
                      <td>
                        <div class="actions">
                          @if (m.run_url) { <a class="btn-quiet" [href]="m.run_url" target="_blank" rel="noopener">MLflow</a> }
                          @if (!m.champion || !v.pinned) {
                            <button class="btn" type="button" (click)="promote(m)" [disabled]="busy()">
                              {{ m.champion ? 'Pin' : (isOlder(m) ? 'Roll back to this' : 'Use this') }}
                            </button>
                          }
                        </div>
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
            <p class="small faint note">
              Rank IC and t-stat are measured on the most recent dates before each version's training data ended, so
              versions trained at different times are tested on different periods. The track record shows how each
              did afterwards.
            </p>
          </section>
        }
        <p class="small faint registry">Registry: {{ v.name }} at {{ v.tracking_uri }}</p>
      }
    }
  `,
  styles: `
    .intro { padding-top: 2rem; }
    .intro p { margin-top: 0.5rem; }
    .mode { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; justify-content: space-between;
            padding: 1rem 1.25rem; border: 1px solid var(--grid-strong); border-radius: 6px; }
    .mode.pinned { border-color: var(--accent); background: var(--accent-wash); }
    tr.current td { background: var(--accent-wash); }
    .chip { margin-left: 0.5rem; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: var(--step--1); }
    .actions { display: flex; gap: 0.75rem; align-items: center; justify-content: flex-end; white-space: nowrap; }
    .date { white-space: nowrap; }
    .registry { overflow-wrap: anywhere; }
    .note { margin-top: 0.75rem; }
  `,
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
