import {
  Component, DestroyRef, ElementRef, HostListener, computed, inject, input, signal,
} from '@angular/core';

import { GLOSSARY, GlossaryKey } from '../core/glossary';

let nextId = 0;
/** Only one hint is open at a time. */
const openHint = signal<number | null>(null);

const SHOW_DELAY = 200;  // ms before a hover opens it (passing the pointer over does nothing)
const HIDE_DELAY = 150;  // ms grace to move the pointer from the button onto the tooltip
const MARGIN = 8;        // px kept between the tooltip and the window edge

/**
 * A small "?" button that explains a term.
 *
 * Follows WCAG 2.2 SC 1.4.13 (content on hover or focus) and the usual tooltip
 * guidance:
 * - it opens on hover (after a short delay), on keyboard focus, and on tap;
 * - it stays open while the pointer is over the button or the tooltip;
 * - Escape, a click elsewhere or scrolling closes it;
 * - it is announced through `aria-describedby`;
 * - it holds a short definition only, never information or actions the page needs.
 *
 * The tooltip is positioned with `position: fixed`, so tables that scroll
 * sideways do not clip it, and it is kept inside the window.
 *
 * Usage: `<app-hint term="ic" />`, or `<app-hint label="Weight" text="…" />`.
 */
@Component({
  selector: 'app-hint',
  template: `
    <span class="hint" (mouseenter)="hoverIn()" (mouseleave)="hoverOut()">
      <button type="button" class="hint-btn" [attr.aria-label]="'About ' + name()"
              [attr.aria-describedby]="open() ? tipId : null" [attr.aria-expanded]="open()"
              (click)="toggle($event)" (focus)="show()" (blur)="hide()"><span class="dot" aria-hidden="true">?</span></button>
      @if (open()) {
        <span class="tip" role="tooltip" [id]="tipId" [class.below]="below()"
              [style.top.px]="top()" [style.left.px]="left()" [style.visibility]="placed() ? 'visible' : 'hidden'">
          @if (heading()) { <strong>{{ heading() }}</strong> }
          {{ body() }}
        </span>
      }
    </span>
  `,
  styles: `
    :host { display: inline-flex; vertical-align: middle; margin-left: 0.25rem; font-weight: 400;
      text-transform: none; letter-spacing: normal; }
    .hint { display: inline-flex; }
    .hint-btn {
      /* 24 × 24 px target (WCAG 2.5.8) around a 16 px circle */
      inline-size: 1.5rem; block-size: 1.5rem; margin: -0.25rem; padding: 0; border: 0; background: none;
      display: inline-grid; place-items: center; cursor: help; color: var(--ink-faint);
    }
    .dot {
      display: grid; place-items: center; inline-size: 1rem; block-size: 1rem; border-radius: 50%;
      border: 1.5px solid currentColor; font: 700 0.65rem/1 var(--font);
    }
    .hint-btn:hover, .hint-btn[aria-expanded='true'] { color: var(--accent); }
    .tip {
      position: fixed; z-index: 50; max-inline-size: min(20rem, calc(100vw - 16px)); inline-size: max-content;
      padding: 0.55rem 0.7rem; border-radius: var(--radius-m);
      background: var(--ink); color: var(--paper); box-shadow: 0 6px 20px rgb(0 0 0 / 0.18);
      font: 400 var(--step--1)/1.45 var(--font); text-align: left; white-space: normal;
    }
    .tip strong { display: block; font-weight: 700; margin-bottom: 0.15rem; }
    @media (prefers-reduced-motion: no-preference) {
      .tip { animation: fade 120ms ease-out; }
      @keyframes fade { from { opacity: 0; } }
    }
  `,
})
export class HintComponent {
  /** A glossary entry (preferred: keeps wording consistent across pages). */
  readonly term = input<GlossaryKey | null>(null);
  /** Or free text, with the name of what it explains. */
  readonly text = input<string>('');
  readonly label = input<string>('');

  private readonly host = inject(ElementRef<HTMLElement>);
  readonly tipId = `hint-${++nextId}`;
  private readonly id = nextId;

  readonly open = computed(() => openHint() === this.id);
  readonly top = signal(0);
  readonly left = signal(0);
  readonly below = signal(false);
  readonly placed = signal(false);

  readonly entry = computed(() => (this.term() ? GLOSSARY[this.term()!] : null));
  readonly name = computed(() => this.label() || this.entry()?.term || 'this');
  readonly heading = computed(() => this.entry()?.term ?? (this.label() || ''));
  readonly body = computed(() => this.text() || this.entry()?.text || '');

  private showTimer: ReturnType<typeof setTimeout> | undefined;
  private hideTimer: ReturnType<typeof setTimeout> | undefined;
  private pinned = false;

  constructor() {
    inject(DestroyRef).onDestroy(() => {
      this.clearTimers();
      if (this.open()) openHint.set(null);
    });
  }

  hoverIn(): void {
    clearTimeout(this.hideTimer);
    if (!this.open()) this.showTimer = setTimeout(() => this.show(), SHOW_DELAY);
  }

  hoverOut(): void {
    clearTimeout(this.showTimer);
    if (!this.pinned) this.hideTimer = setTimeout(() => this.close(), HIDE_DELAY);
  }

  show(): void {
    this.clearTimers();
    if (this.open()) return;
    this.placed.set(false);
    openHint.set(this.id);
    requestAnimationFrame(() => this.place());
  }

  hide(): void {
    if (!this.pinned) this.close();
  }

  toggle(event: Event): void {
    event.stopPropagation();
    if (this.open() && this.pinned) {
      this.close();
    } else {
      this.pinned = true;
      this.show();
    }
  }

  close(): void {
    this.clearTimers();
    this.pinned = false;
    if (this.open()) openHint.set(null);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.close();
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: Event): void {
    if (this.open() && !this.host.nativeElement.contains(event.target as Node)) this.close();
  }

  @HostListener('window:scroll')
  @HostListener('window:resize')
  onViewportChange(): void {
    if (this.open()) this.close();
  }

  /** Above the button when there is room, otherwise below; always inside the window. */
  private place(): void {
    const root = this.host.nativeElement as HTMLElement;
    const button = root.querySelector('.hint-btn');
    const tip = root.querySelector('.tip') as HTMLElement | null;
    if (!button || !tip) return;
    const b = button.getBoundingClientRect();
    const t = tip.getBoundingClientRect();
    const below = b.top - t.height - MARGIN < 0;
    this.below.set(below);
    this.top.set(below ? b.bottom + 6 : b.top - t.height - 6);
    const centred = b.left + b.width / 2 - t.width / 2;
    this.left.set(Math.max(MARGIN, Math.min(centred, window.innerWidth - t.width - MARGIN)));
    this.placed.set(true);
  }

  private clearTimers(): void {
    clearTimeout(this.showTimer);
    clearTimeout(this.hideTimer);
  }
}
