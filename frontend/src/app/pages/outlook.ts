import { Component, computed, inject, signal } from '@angular/core';
import { ChartConfiguration } from 'chart.js';
import { RouterLink } from '@angular/router';

import { compact, num, pct, price, shortDate } from '../core/format';
import { RankedAsset } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { UniverseStores } from '../core/universe-store';
import { ChartComponent, baseOptions, themeColors } from '../shared/chart';
import { EvidenceMeterComponent } from '../shared/evidence-meter';
import { ScoreBarComponent } from '../shared/score-bar';

@Component({
  selector: 'app-outlook',
  imports: [RouterLink, EvidenceMeterComponent, ScoreBarComponent, ChartComponent],
  templateUrl: './outlook.html',
  styleUrl: './outlook.scss',
})
export class OutlookPage {
  readonly universe = injectUniverse();
  readonly store = inject(UniverseStores).get(this.universe);
  readonly expanded = signal<string | null>(null);
  readonly showAll = signal(false);

  readonly analysis = this.store.analysis;
  readonly quality = computed(() => this.analysis()?.summary.model_quality ?? {});
  readonly rest = computed(() => (this.analysis()?.rankings ?? []).filter((r) => !r.picked));
  readonly horizonEnd = computed(() => {
    const a = this.analysis();
    if (!a) return '';
    const days = this.universe === 'crypto' ? a.run.horizon : Math.round(a.run.horizon * 7 / 5);
    const end = new Date(a.run.data_date + 'T12:00:00');
    end.setDate(end.getDate() + days);
    return shortDate(end.toISOString().slice(0, 10));
  });

  readonly calibrationChart = computed<ChartConfiguration | null>(() => {
    const rows = this.analysis()?.summary.calibration ?? [];
    if (!rows.length) return null;
    const c = themeColors();
    const options = baseOptions((v) => pct(v, 0)) as ChartConfiguration['options'];
    return {
      type: 'line',
      data: {
        labels: rows.map((r) => pct(r.predicted, 0)),
        datasets: [
          { label: 'Observed', data: rows.map((r) => r.observed), borderColor: c.accent, backgroundColor: c.accent,
            pointRadius: 4, borderWidth: 2 },
          { label: 'Perfect calibration', data: rows.map((r) => r.predicted), borderColor: c.faint,
            borderDash: [4, 4], pointRadius: 0, borderWidth: 1 },
        ],
      },
      options: { ...options, scales: { ...options!.scales, x: { ...options!.scales!['x'],
        title: { display: true, text: 'Predicted chance', color: c.faint } } } },
    };
  });

  toggle(symbol: string): void {
    this.expanded.set(this.expanded() === symbol ? null : symbol);
  }

  maxContribution(asset: RankedAsset): number {
    return Math.max(0.0001, ...asset.explanation.map((e) => Math.abs(e.contribution)));
  }

  featureValue(feature: string, value: number): string {
    if (/ROC|vs_|Return|Distance|Pct|Gap|Range_Pct/.test(feature) && !/RSI|Rank|Position/.test(feature)) {
      return /ROC/.test(feature) ? num(value, 1, true) + '%' : pct(value, 1, true);
    }
    return num(value, 2);
  }

  readonly pct = pct;
  readonly num = num;
  readonly price = price;
  readonly compact = compact;
  readonly shortDate = shortDate;
  readonly Math = Math;
}
