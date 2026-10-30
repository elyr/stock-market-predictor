import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { GLOSSARY } from '../core/glossary';
import { HintComponent } from './hint';

@Component({
  imports: [HintComponent],
  template: `<p>Rank IC <app-hint term="ic" /></p><p>Weight <app-hint label="Weight" text="Share of the portfolio." /></p>
             <button class="outside">elsewhere</button>`,
})
class Host {}

describe('HintComponent', () => {
  function render() {
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const buttons = Array.from(root.querySelectorAll<HTMLButtonElement>('.hint-btn'));
    return { fixture, root, buttons };
  }

  it('names the button after the term and keeps the tooltip closed at first', () => {
    const { root, buttons } = render();
    expect(buttons[0].getAttribute('aria-label')).toBe('About Rank IC');
    expect(buttons[1].getAttribute('aria-label')).toBe('About Weight');
    expect(buttons[0].getAttribute('type')).toBe('button');
    expect(root.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('opens on keyboard focus, describes the button, and closes on blur', () => {
    const { fixture, root, buttons } = render();
    buttons[0].dispatchEvent(new Event('focus'));
    fixture.detectChanges();
    const tip = root.querySelector('[role="tooltip"]')!;
    expect(tip.textContent).toContain(GLOSSARY.ic.text);
    expect(buttons[0].getAttribute('aria-describedby')).toBe(tip.id);
    expect(buttons[0].getAttribute('aria-expanded')).toBe('true');
    buttons[0].dispatchEvent(new Event('blur'));
    fixture.detectChanges();
    expect(root.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('stays open after a tap until Escape', () => {
    const { fixture, root, buttons } = render();
    buttons[1].click();
    buttons[1].dispatchEvent(new Event('blur'));
    fixture.detectChanges();
    expect(root.querySelector('[role="tooltip"]')?.textContent).toContain('Share of the portfolio.');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();
    expect(root.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('shows one tooltip at a time and closes on a click elsewhere', () => {
    const { fixture, root, buttons } = render();
    buttons[0].click();
    fixture.detectChanges();
    buttons[1].click();
    fixture.detectChanges();
    const tips = root.querySelectorAll('[role="tooltip"]');
    expect(tips.length).toBe(1);
    expect(tips[0].textContent).toContain('Share of the portfolio.');
    (root.querySelector('.outside') as HTMLElement).click();
    fixture.detectChanges();
    expect(root.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('a second tap closes it', () => {
    const { fixture, root, buttons } = render();
    buttons[0].click();
    fixture.detectChanges();
    buttons[0].click();
    fixture.detectChanges();
    expect(root.querySelector('[role="tooltip"]')).toBeNull();
  });
});

describe('Glossary', () => {
  it('keeps every definition short enough for a tooltip', () => {
    for (const [key, entry] of Object.entries(GLOSSARY)) {
      expect(entry.term.length, key).toBeGreaterThan(0);
      expect(entry.text.length, key).toBeLessThanOrEqual(280);
    }
  });
});
