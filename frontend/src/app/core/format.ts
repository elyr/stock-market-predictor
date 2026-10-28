/** Number formatting shared by templates (all locale-aware, tabular figures come from CSS). */

const dash = '–';

export function pct(value: number | null | undefined, digits = 1, signed = false): string {
  if (value == null || Number.isNaN(value)) return dash;
  const text = (value * 100).toFixed(digits) + '%';
  return signed && value > 0 ? '+' + text : text;
}

export function num(value: number | null | undefined, digits = 2, signed = false): string {
  if (value == null || Number.isNaN(value)) return dash;
  const text = value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return signed && value > 0 ? '+' + text : text;
}

export function price(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return dash;
  const digits = value < 1 ? 4 : value < 100 ? 2 : value < 10000 ? 2 : 0;
  return '$' + value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function bps(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return dash;
  return (value > 0 ? '+' : '') + value.toFixed(1) + ' bp';
}

export function compact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return dash;
  return Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return dash;
  const date = new Date(value.length === 10 ? value + 'T12:00:00' : value);
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

/** How strongly a t-statistic supports a real effect, in plain words. */
export function evidence(t: number | null | undefined): { label: string; tone: 'strong' | 'weak' | 'none' | 'negative' } {
  if (t == null || Number.isNaN(t)) return { label: 'Not enough data yet', tone: 'none' };
  if (t >= 3) return { label: 'Strong evidence of skill', tone: 'strong' };
  if (t >= 2) return { label: 'Some evidence of skill', tone: 'weak' };
  if (t > -2) return { label: 'Indistinguishable from luck', tone: 'none' };
  return { label: 'Consistently wrong', tone: 'negative' };
}
