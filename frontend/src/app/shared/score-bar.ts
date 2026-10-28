import { Component, input } from '@angular/core';

/** A 0–100 score as a short filled bar with its value. */
@Component({
  selector: 'app-score-bar',
  template: `<span class="bar" [attr.aria-label]="label() + ' ' + value().toFixed(0) + ' of 100'">
    <span class="bar-track"><span class="bar-fill" [style.width.%]="value()"></span></span>
    <span class="val">{{ value().toFixed(0) }}</span>
  </span>`,
  styles: `.val { width: 1.6rem; text-align: right; font-weight: 600; }`,
})
export class ScoreBarComponent {
  readonly value = input.required<number>();
  readonly label = input('Score');
}
