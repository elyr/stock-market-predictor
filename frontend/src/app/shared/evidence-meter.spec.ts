import { TestBed } from '@angular/core/testing';

import { EvidenceMeterComponent } from './evidence-meter';

describe('EvidenceMeterComponent', () => {
  function render(ic: number, t: number, days = 100) {
    const fixture = TestBed.createComponent(EvidenceMeterComponent);
    fixture.componentRef.setInput('ic', ic);
    fixture.componentRef.setInput('t', t);
    fixture.componentRef.setInput('icStd', 0.2);
    fixture.componentRef.setInput('days', days);
    fixture.componentRef.setInput('positiveShare', 0.55);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('calls an IC inside the luck band indistinguishable from luck', () => {
    const el = render(0.01, 0.5);
    expect(el.textContent).toContain('Indistinguishable from luck');
    expect(el.querySelector('.marker')?.className).toContain('tone-none');
  });

  it('marks strong positive evidence and places the marker right of zero', () => {
    const el = render(0.06, 3.4);
    expect(el.textContent).toContain('Strong evidence of skill');
    const left = parseFloat((el.querySelector('.marker') as HTMLElement).style.left);
    expect(left).toBeGreaterThan(50);
  });

  it('sizes the luck band from the IC standard error', () => {
    const narrow = parseFloat((render(0, 0, 400).querySelector('.luck') as HTMLElement).style.width);
    const wide = parseFloat((render(0, 0, 25).querySelector('.luck') as HTMLElement).style.width);
    expect(wide).toBeGreaterThan(narrow);
  });
});
