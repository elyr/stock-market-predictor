import { fixtures } from '../../testing/api-fixtures';
import { TrendView } from './models';

describe('trend fixtures', () => {
  for (const universe of ['stocks', 'crypto'] as const) {
    it(`${universe} matches the TrendView type`, () => {
      const view = fixtures[universe].trend as TrendView;
      expect(view.universe).toBe(universe);
      expect(view.record?.days).toBeGreaterThan(view.criteria.min_history_days);
      expect(view.reasons.length).toBeGreaterThan(0);
      expect(view.assets.every(a => a.state === 'in' || a.state === 'out')).toBe(true);
    });
  }
});
