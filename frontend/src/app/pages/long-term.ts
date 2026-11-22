import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../core/api.service';
import { evidence, num, pct, price, shortDate } from '../core/format';
import { LongTermView } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { describeError } from '../core/universe-store';
import { EvidenceMeterComponent } from '../shared/evidence-meter';
import { HintComponent } from '../shared/hint';
import { ScoreBarComponent } from '../shared/score-bar';

/** The ranking for the month ahead, from a second model, with its own evidence. */
@Component({
  selector: 'app-long-term',
  imports: [RouterLink, EvidenceMeterComponent, HintComponent, ScoreBarComponent],
  templateUrl: './long-term.html',
  styleUrl: './long-term.scss',
})
export class LongTermPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly view = signal<LongTermView | null>(null);
  readonly missing = signal(false);
  readonly error = signal<string | null>(null);
  readonly all = signal(false);

  ngOnInit(): void {
    this.api.longTerm(this.universe).subscribe({
      next: (v) => this.view.set(v),
      error: (err) => (err?.status === 404 ? this.missing.set(true) : this.error.set(describeError(err))),
    });
  }

  readonly verdict = computed(() => evidence(this.view()?.model_quality.ic_t_stat));
  readonly shown = computed(() => (this.all() ? this.view()?.assets ?? [] : (this.view()?.assets ?? []).slice(0, 15)));
  readonly maxWeight = computed(() => Math.max(1e-9, ...(this.view()?.weights ?? []).map((w) => Math.abs(w.weight))));
  readonly independent = computed(() => {
    const q = this.view()?.model_quality;
    return Math.round(q?.ic_independent_periods ?? q?.ic_days ?? 0);
  });

  abs(value: number): number {
    return Math.abs(value);
  }

  readonly num = num;
  readonly pct = pct;
  readonly price = price;
  readonly shortDate = shortDate;
}
