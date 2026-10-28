import { Component, computed, input } from '@angular/core';

import { evidence, num, pct } from '../core/format';

/**
 * Places the model's out-of-sample information coefficient on a scale.
 * The shaded band is the range that pure luck would produce about 95% of the
 * time (|t| < 2), so a marker inside it means "no proven skill yet".
 */
@Component({
  selector: 'app-evidence-meter',
  template: `
    <figure class="meter" [attr.aria-label]="ariaLabel()">
      <div class="scale">
        <div class="luck" [style.left.%]="pos(-band())" [style.width.%]="pos(band()) - pos(-band())"></div>
        <div class="zero" [style.left.%]="50"></div>
        <div class="marker" [class]="'marker tone-' + verdict().tone" [style.left.%]="pos(ic())">
          <span class="marker-value">{{ fmt(ic()) }}</span>
        </div>
      </div>
      <div class="ticks"><span>{{ fmt(-range) }}</span><span>0</span><span>{{ fmt(range) }}</span></div>
      <figcaption>
        <strong [class]="'tone-' + verdict().tone">{{ verdict().label }}.</strong>
        Across {{ days() }} unseen {{ days() === 1 ? 'date' : 'dates' }}, the model's ranking correlated
        {{ ic() >= 0 ? 'positively' : 'negatively' }} with what happened next
        (rank IC {{ fmt(ic()) }}, t = {{ t() == null ? '–' : num(t()!, 1) }}).
        The shaded band is what luck alone produces.
        @if (positiveShare() != null) {
          It was right more often than wrong on {{ pct(positiveShare()!, 0) }} of dates.
        }
      </figcaption>
    </figure>
  `,
  styles: `
    .meter { margin: 0; }
    .scale { position: relative; height: 2.75rem; border-bottom: 1px solid var(--grid-strong); }
    .luck { position: absolute; top: 0.9rem; bottom: 0; background: var(--luck);
      background-image: repeating-linear-gradient(135deg, transparent 0 6px, var(--grid) 6px 7px); }
    .zero { position: absolute; top: 0.5rem; bottom: 0; width: 1px; background: var(--grid-strong); }
    .marker { position: absolute; top: 0; bottom: 0; width: 3px; margin-left: -1px; background: var(--ink); }
    .marker-value { position: absolute; top: -0.2rem; left: 0.4rem; font-weight: 700; font-size: var(--step--1); white-space: nowrap; }
    .tone-strong { color: var(--up); } .marker.tone-strong { background: var(--up); }
    .tone-weak { color: var(--up); } .marker.tone-weak { background: var(--up); }
    .tone-negative { color: var(--down); } .marker.tone-negative { background: var(--down); }
    .tone-none { color: var(--ink); }
    .ticks { display: flex; justify-content: space-between; font-size: var(--step--1); color: var(--ink-faint); margin-top: 0.25rem; }
    figcaption { margin-top: 0.9rem; max-width: 68ch; color: var(--ink-soft); }
    figcaption strong { font-weight: 700; }
  `,
})
export class EvidenceMeterComponent {
  readonly ic = input.required<number>();
  readonly t = input<number | null | undefined>(null);
  readonly icStd = input<number | null | undefined>(null);
  readonly days = input(0);
  readonly positiveShare = input<number | null | undefined>(null);

  readonly range = 0.15;
  readonly verdict = computed(() => evidence(this.t()));
  /** Half-width of the luck band: 2 standard errors of the mean IC. */
  readonly band = computed(() => {
    const std = this.icStd();
    const n = this.days();
    if (!std || !n) return 0.03;
    return Math.min(this.range, (2 * std) / Math.sqrt(n));
  });
  readonly ariaLabel = computed(() => `Rank IC ${this.fmt(this.ic())}: ${this.verdict().label}`);

  pos(value: number): number {
    const clamped = Math.max(-this.range, Math.min(this.range, value));
    return ((clamped + this.range) / (2 * this.range)) * 100;
  }

  fmt(value: number): string {
    return (value > 0 ? '+' : '') + value.toFixed(3);
  }

  readonly num = num;
  readonly pct = pct;
}
