import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../core/api.service';
import { pct, price } from '../core/format';
import { Brief } from '../core/models';
import { injectUniverse } from '../core/route-universe';
import { describeError } from '../core/universe-store';

/** The week in plain sentences, ending with what to do (often: nothing). */
@Component({
  selector: 'app-brief',
  imports: [RouterLink],
  templateUrl: './brief.html',
  styleUrl: './brief.scss',
})
export class BriefPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly universe = injectUniverse();
  readonly brief = signal<Brief | null>(null);
  readonly error = signal<string | null>(null);
  readonly markdownUrl = this.api.briefMarkdownUrl(this.universe);

  ngOnInit(): void {
    this.api.brief(this.universe).subscribe({
      next: (b) => this.brief.set(b),
      error: (err) => this.error.set(describeError(err)),
    });
  }

  readonly pct = pct;
  readonly price = price;
}
