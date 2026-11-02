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
  template: `
    @if (error(); as e) { <p class="notice error page-gap" role="alert">{{ e }}</p> }
    @if (!brief() && !error()) { <p class="muted page-gap"><span class="spinner" aria-hidden="true"></span> Writing your brief</p> }

    @if (brief(); as b) {
      <article class="brief">
        <header class="section intro">
          <h2>{{ b.title }}</h2>
          <p class="muted">{{ b.subtitle }} Built from Ledger's own data with fixed rules, so every sentence comes from a number you can check on the other pages.</p>
        </header>

        <section class="actions-card" aria-labelledby="todo-title">
          <h3 id="todo-title">What to do</h3>
          <ol>
            @for (a of b.actions; track a) { <li>{{ a }}</li> }
          </ol>
        </section>

        @for (s of b.sections; track s.title) {
          <section class="section part">
            <h3>{{ s.title }}</h3>
            @for (line of s.lines; track line) { <p>{{ line }}</p> }
            @if (s.ideas?.length) {
              <ul class="ideas">
                @for (i of s.ideas; track i.symbol) {
                  <li>
                    <a class="asset-link" [routerLink]="['../asset', i.symbol]">{{ i.symbol }}</a>
                    <span class="muted">{{ pct(i.chance, 0) }} chance to beat the average</span>
                    @if (i.low != null) { <span class="faint">next week {{ price(i.low) }} – {{ price(i.high) }}</span> }
                  </li>
                }
              </ul>
            }
            @if (s.title === 'Your portfolio') {
              <p><a routerLink="../portfolio">Open My portfolio</a></p>
            }
            @if (s.title === 'Is the model working?') {
              <p><a routerLink="../track-record">See the track record</a></p>
            }
          </section>
        }

        <footer class="small faint foot">
          <a class="btn btn-quiet" [href]="markdownUrl" download>Download as Markdown</a>
          Research tool, not financial advice.
        </footer>
      </article>
    }
  `,
  styles: `
    .brief { max-width: 46rem; }
    .intro { padding-top: 2rem; }
    .intro p { margin-top: 0.5rem; }
    .actions-card { margin: 0.5rem 0 1rem; padding: 1rem 1.25rem; border-radius: var(--radius-m);
      background: var(--accent-wash); border: 1px solid var(--grid); }
    .actions-card h3 { margin: 0 0 0.5rem; }
    .actions-card ol { margin: 0; padding-left: 1.25rem; display: grid; gap: 0.4rem; }
    .part p { margin: 0.4rem 0; line-height: 1.6; }
    .ideas { list-style: none; padding: 0; margin: 0.5rem 0; display: grid; gap: 0.35rem; }
    .ideas li { display: flex; flex-wrap: wrap; gap: 0.25rem 0.75rem; align-items: baseline; }
    .asset-link { font-weight: 700; text-decoration: none; color: var(--accent); }
    .foot { display: flex; gap: 1rem; align-items: center; padding: 1rem 0 2rem; }
    .page-gap { margin-top: 2rem; }
  `,
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
