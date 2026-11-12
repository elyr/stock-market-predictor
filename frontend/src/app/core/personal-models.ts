// Types for your portfolio, the weekly brief and the long-term view.
import type { ModelQuality, Universe } from './models';

// ------------------------------------------------------------------ portfolio

export interface Transaction {
  id: string;
  universe: Universe;
  symbol: string;
  side: 'buy' | 'sell';
  trade_date: string;
  quantity: number;
  price: number;
  fees: number;
  note: string | null;
  created_at: string;
}

export interface NewTransaction {
  symbol: string;
  side: 'buy' | 'sell';
  trade_date: string;
  quantity: number;
  price: number;
  fees: number;
  note: string | null;
}

export interface Position {
  symbol: string;
  name: string;
  sector: string | null;
  quantity: number;
  average_cost: number | null;
  price: number | null;
  value: number | null;
  cost_basis: number;
  unrealized: number;
  unrealized_pct: number | null;
  realized: number;
  fees: number;
  first_date: string;
  trades: number;
  weight: number;
  rank: number | null;
  universe_size: number | null;
  score: number | null;
  beat_probability: number | null;
  picked: boolean;
  vol_forecast: number | null;
  vol_up_probability: number | null;
  week_range: { low: number; high: number; days: number } | null;
}

export interface PortfolioWarning {
  level: 'high' | 'medium' | 'info';
  kind: string;
  message: string;
  symbol: string | null;
}

export interface PortfolioSummary {
  value: number;
  invested: number | null;
  bought: number;
  gain: number;
  unrealized: number;
  realized: number;
  gain_pct: number | null;
  benchmark_value: number | null;
  vs_benchmark: number | null;
  volatility: number | null;
  risk_label: string | null;
  next_week: { low: number; high: number; days: number } | null;
  positions: number;
  as_of: string | null;
  since: string;
}

export interface PortfolioView {
  universe: Universe;
  empty: boolean;
  rules: { max_position: number; max_sector: number; max_volatility: number; min_positions: number };
  benchmark_label: string;
  symbols: string[];
  transactions: Transaction[];
  summary: PortfolioSummary | null;
  positions: Position[];
  warnings: PortfolioWarning[];
  sectors: { sector: string; weight: number }[];
  history: { date: string; value: number; invested: number; benchmark: number | null }[];
}

// ---------------------------------------------------------------------- brief

export interface BriefSection {
  title: string;
  lines: string[];
  warnings?: PortfolioWarning[];
  picks?: { symbol: string; name: string; chance: number | null; price: number | null; low: number | null; high: number | null }[];
}

export interface Brief {
  universe: Universe;
  as_of: string | null;
  title: string;
  subtitle: string;
  sections: BriefSection[];
  actions: string[];
}

// ------------------------------------------------------------------ long term

export interface LongTermAsset {
  symbol: string;
  name: string;
  sector: string | null;
  price: number | null;
  score: number;
  probability: number | null;
  rank: number;
  short_rank: number | null;
  picked: boolean;
  volatility: number | null;
}

export interface LongTermView {
  data_date: string;
  horizon_days: number;
  short_horizon_days: number;
  model_quality: ModelQuality;
  weights: { feature: string; label: string; weight: number }[];
  assets: LongTermAsset[];
}
