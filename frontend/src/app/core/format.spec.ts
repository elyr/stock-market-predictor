import { bps, evidence, pct, price } from './format';

describe('format', () => {
  it('formats percentages with optional sign and dash for missing values', () => {
    expect(pct(0.1234)).toBe('12.3%');
    expect(pct(0.05, 0, true)).toBe('+5%');
    expect(pct(-0.05, 1, true)).toBe('-5.0%');
    expect(pct(null)).toBe('–');
  });

  it('formats prices for very small and large assets', () => {
    expect(price(0.1234)).toBe('$0.1234');
    expect(price(64250.4)).toMatch(/^\$64,250$/);
  });

  it('formats basis points', () => {
    expect(bps(12.34)).toBe('+12.3 bp');
  });

  it('turns a t-statistic into a plain verdict', () => {
    expect(evidence(3.2).tone).toBe('strong');
    expect(evidence(2.1).label).toBe('Some evidence of skill');
    expect(evidence(0.4).label).toBe('Indistinguishable from luck');
    expect(evidence(-2.5).tone).toBe('negative');
    expect(evidence(null).tone).toBe('none');
  });
});
