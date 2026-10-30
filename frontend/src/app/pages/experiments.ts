import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { ApiService } from '../core/api.service';
import { evidence, num, pct, shortDate } from '../core/format';
import { Experiment, SettingSpec } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { UniverseStores, describeError } from '../core/universe-store';
import { HintComponent } from '../shared/hint';

/** Settings shown in the form, in display order. Others are available through the API. */
const FORM_KEYS = [
  'ml_config.model',
  'ml_config.cross_section.ridge.alpha',
  'ranking_config.weights.ml_prediction',
  'ranking_config.weights.technical_score',
  'ranking_config.weights.momentum_score',
  'ranking_config.weights.volume_score',
  'ml_config.training.horizon',
  'portfolio.weighting',
  'portfolio.max_per_sector',
];

@Component({
  selector: 'app-experiments',
  imports: [FormsModule, RouterLink, HintComponent],
  templateUrl: './experiments.html',
  styleUrl: './experiments.scss',
})
export class ExperimentsPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly store = inject(UniverseStores).get(this.universe);

  readonly experiments = signal<Experiment[]>([]);
  readonly specs = signal<Record<string, SettingSpec>>({});
  readonly periods = signal<{ lockbox_days: number; test_days: number } | null>(null);
  readonly busy = signal<Record<string, boolean>>({});
  readonly error = signal<string | null>(null);
  readonly submitting = signal(false);

  name = '';
  topN: number | null = null;
  values: Record<string, string | number | null> = {};

  readonly fields = computed(() => {
    const specs = this.specs();
    return FORM_KEYS.filter((k) => specs[k]).map((key) => ({ key, spec: specs[key] }));
  });

  readonly baseline = computed(() => this.experiments().find((e) => !Object.keys(e.settings).length && e.status === 'done'));
  readonly best = computed(() => {
    const done = this.experiments().filter((e) => e.development?.headline.ic_mean != null);
    return done.sort((a, b) => (b.development!.headline.ic_mean ?? -1) - (a.development!.headline.ic_mean ?? -1))[0]?.id;
  });
  readonly windows = computed(() => this.experiments().find((e) => e.development)?.development?.windows ?? null);
  readonly lockboxChecks = computed(() => this.experiments().filter((e) => e.lockbox).length);

  ngOnInit(): void {
    this.api.experimentSettings().subscribe({ next: (s) => this.specs.set(s), error: (e) => this.error.set(describeError(e)) });
    this.load();
  }

  load(): void {
    this.api.experiments(this.universe).subscribe({
      next: (r) => {
        this.experiments.set(r.experiments);
        this.periods.set({ lockbox_days: r.lockbox_days, test_days: r.test_days });
        for (const e of r.experiments) {
          if ((e.status === 'queued' || e.status === 'running') && !this.busy()[e.id]) this.poll(e.id);
        }
      },
      error: (e) => this.error.set(describeError(e)),
    });
  }

  /** Short help for the settings whose meaning is not obvious from the label. */
  readonly fieldHelp: Record<string, string> = {
    'ml_config.model': 'Cross section: the current model, which compares assets on ten ranked inputs. Legacy: the earlier ensemble of classifiers on ~86 indicators, kept for comparison.',
    'ml_config.cross_section.ridge.alpha': 'How strongly the model is held back from trusting any one input. Higher is more cautious; lower lets it fit the past more closely, which risks fitting noise.',
    'ranking_config.weights.ml_prediction': 'How much the model counts in the final score. Weights are relative to each other.',
    'ranking_config.weights.technical_score': 'Rule-based reading of RSI, MACD, Bollinger bands and moving averages. 0 by default because the model already uses these ideas.',
    'ranking_config.weights.momentum_score': 'Rule-based reading of recent returns. 0 by default: over a week it tends to point the wrong way.',
    'ranking_config.weights.volume_score': 'Rule-based reading of trading volume. 0 by default.',
    'ml_config.training.horizon': 'How many days ahead the model predicts and how long picks are held.',
    'portfolio.weighting': 'Equal: every pick gets the same share. Inverse volatility: calmer picks get more, so each carries similar risk.',
    'portfolio.max_per_sector': 'At most this many picks from one sector, to avoid one bet on a whole industry. 0 means no limit.',
  };

  currentValue(key: string): string {
    const info = this.store.info();
    if (!info) return '';
    if (key.startsWith('ranking_config.weights.')) return String(info.weights[key.split('.').pop()!] ?? '');
    if (key === 'ml_config.training.horizon') return String(info.horizon_days);
    if (key === 'ml_config.model') return (info.model ?? 'cross_section').replace('_', ' ');
    if (key === 'ml_config.cross_section.ridge.alpha') return String(info.ridge_alpha ?? '');
    if (key === 'portfolio.weighting') return info.portfolio?.weighting ?? '';
    if (key === 'portfolio.max_per_sector') return String(info.portfolio?.max_per_sector ?? '');
    return '';
  }

  runBaseline(): void {
    this.submit('Current settings', {});
  }

  run(): void {
    const settings: Record<string, unknown> = {};
    for (const { key, spec } of this.fields()) {
      const value = this.values[key];
      if (value === null || value === undefined || value === '') continue;
      settings[key] = spec.type === 'int' || spec.type === 'float' ? Number(value) : value;
    }
    const name = this.name.trim() || this.describe(settings) || 'Current settings';
    this.submit(name, settings);
  }

  private submit(name: string, settings: Record<string, unknown>): void {
    this.error.set(null);
    this.submitting.set(true);
    this.api.createExperiment(this.universe, { name, settings, top_n: this.topN }).subscribe({
      next: (r) => {
        this.submitting.set(false);
        this.name = '';
        this.values = {};
        this.load();
        this.poll(r.experiment_id, r.job.id);
      },
      error: (e) => { this.submitting.set(false); this.error.set(describeError(e)); },
    });
  }

  checkLockbox(experiment: Experiment): void {
    this.api.checkLockbox(this.universe, experiment.id).subscribe({
      next: (job) => this.poll(experiment.id, job.id),
      error: (e) => this.error.set(describeError(e)),
    });
  }

  private poll(experimentId: string, jobId?: string): void {
    this.busy.update((b) => ({ ...b, [experimentId]: true }));
    const done = () => {
      this.busy.update((b) => ({ ...b, [experimentId]: false }));
      this.load();
    };
    if (!jobId) {
      setTimeout(done, 5000);
      return;
    }
    this.api.watchJob(jobId).subscribe({
      next: (job) => {
        if (job.status === 'failed') this.error.set(job.error ?? 'The experiment failed.');
        if (job.status === 'succeeded' || job.status === 'failed') done();
      },
      error: () => done(),
    });
  }

  describe(settings: Record<string, unknown>): string {
    const specs = this.specs();
    return Object.entries(settings)
      .map(([k, v]) => `${(specs[k]?.label ?? k).replace('Weight: ', '').toLowerCase()} ${v}`)
      .join(', ');
  }

  changes(e: Experiment): string {
    const text = this.describe(e.settings);
    return (text || 'No changes') + (e.top_n ? `, top ${e.top_n}` : '');
  }

  delta(e: Experiment): number | null {
    const base = this.baseline()?.development?.headline.ic_mean;
    const mine = e.development?.headline.ic_mean;
    return base == null || mine == null || e.id === this.baseline()?.id ? null : mine - base;
  }

  holdUp(e: Experiment): { label: string; tone: string } | null {
    if (!e.lockbox || !e.development) return null;
    const dev = e.development.headline.ic_mean ?? 0;
    const locked = e.lockbox.headline.ic_mean ?? 0;
    if (locked <= 0) return { label: 'Did not hold up', tone: 'down' };
    if (dev > 0 && locked >= dev * 0.5) return { label: 'Held up', tone: 'up' };
    return { label: 'Weakened', tone: 'muted' };
  }

  readonly pct = pct;
  readonly num = num;
  readonly shortDate = shortDate;
  readonly evidence = evidence;
}
