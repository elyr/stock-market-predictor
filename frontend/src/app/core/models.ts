export type Universe = 'stocks' | 'crypto';

export interface UniverseInfo {
  key: Universe;
  label: string;
  symbols: string[];
  symbol_count: number;
  horizon_days: number;
  target: 'relative' | 'absolute';
  periods_per_year: number;
  top_picks: number;
  weights: Record<string, number>;
  use_sentiment: boolean;
  latest_run_at: string | null;
  demo: boolean;
}

export interface Contribution {
  feature: string;
  label: string;
  value: number;
  contribution: number;
}

export interface RankedAsset {
  symbol: string;
  company_name: string;
  sector: string;
  asset_class: Universe;
  current_price: number;
  daily_change_pct: number;
  volume: number;
  composite_score: number;
  technical_score: number;
  ml_score: number;
  ml_probability: number | null;
  ml_confidence: number;
  momentum_score: number;
  volume_score: number;
  sentiment_score: number | null;
  rsi: number | null;
  volatility: number | null;
  vol_forecast: number | null;
  vol_up_probability: number | null;
  recommendation: string;
  signals: string[];
  explanation: Contribution[];
  horizon_days: number;
  data_date: string;
  rank: number;
  picked: boolean;
  weight: number | null;
  realized_return: number | null;
}

export interface ModelQuality {
  test_accuracy?: number;
  test_auc?: number | null;
  test_base_rate?: number;
  brier_raw?: number;
  brier_calibrated?: number;
  test_rows?: number;
  test_start?: string;
  test_end?: string;
  ic_mean?: number;
  ic_std?: number;
  ic_t_stat?: number;
  ic_positive_share?: number;
  ic_days?: number;
}

export interface VolatilityModel {
  accuracy: number;
  base_rate: number;
  auc: number | null;
  r2_model: number;
  r2_naive: number;
  test_rows: number;
  horizon: number;
}

export interface AnalysisSummary {
  universe: Universe;
  label: string;
  total_analyzed: number;
  analysis_date: string;
  data_date: string;
  horizon_days: number;
  target: string;
  market_sentiment: string;
  model_quality: ModelQuality;
  calibration: { predicted: number; observed: number; count: number }[];
  volatility_model: VolatilityModel | Record<string, never>;
  top_features: { feature: string; importance: number }[];
  ml_models_used: string[];
}

export interface Run {
  id: string;
  universe: Universe;
  created_at: string;
  data_date: string;
  horizon: number;
  top_n: number;
  demo: boolean;
  simulated: boolean;
  evaluated_at: string | null;
  exit_date: string | null;
  portfolio_return: number | null;
  universe_return: number | null;
  excess_return: number | null;
  rank_ic: number | null;
}

export interface Analysis {
  run: Run;
  summary: AnalysisSummary;
  picks: RankedAsset[];
  rankings: RankedAsset[];
}

export interface Job {
  id: string;
  kind: string;
  universe: Universe;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  message: string;
  created_at: string;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface HistoryPoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  sma_20: number | null;
  sma_50: number | null;
  sma_200: number | null;
  bb_upper: number | null;
  bb_lower: number | null;
  rsi: number | null;
  macd: number | null;
  macd_signal: number | null;
}

export interface AssetDetail {
  symbol: string;
  universe: Universe;
  name: string;
  history: HistoryPoint[];
  latest: RankedAsset | null;
  run: Run | null;
  signals: string[];
}

export interface BacktestMetric {
  strategy: string;
  total_return: number;
  annualized_return: number;
  annualized_volatility: number;
  sharpe: number | null;
  max_drawdown: number;
  avg_excess_bps: number;
  excess_t_stat: number | null;
  periods_beating_universe: number | null;
}

export interface BacktestResult {
  settings: {
    universe: Universe; start: string; end: string; periods: number; horizon: number;
    universe_size: number; top_n: number; cost_bps: number; use_ml: boolean; weighting: string;
  };
  headline: { annualized_return: number | null; excess_t_stat: number | null; avg_excess_bps: number | null; ic_mean: number | null };
  metrics: BacktestMetric[];
  ic: { score: string; ic_mean: number; ic_t_stat: number | null; ic_positive_share: number; ic_ir: number | null; periods: number }[];
  dates: string[];
  curves: Record<string, { label: string; values: number[] }>;
  periods: Record<string, number | string | null>[];
  picks: { date: string; rank: number; symbol: string; weight: number; score: number; return: number }[];
}

export interface BacktestRecord {
  id: string;
  universe: Universe;
  created_at: string;
  demo: boolean;
  params: Record<string, unknown>;
  result: BacktestResult;
}

export interface BacktestListItem {
  id: string;
  created_at: string;
  settings: BacktestResult['settings'];
  headline: BacktestResult['headline'];
}

export interface TrackSummary {
  evaluated: number;
  pending: number;
  avg_excess_return?: number;
  excess_t_stat?: number | null;
  hit_rate?: number;
  avg_rank_ic?: number | null;
  curve?: { date: string; portfolio: number; universe: number }[];
}

export interface TrackRecord {
  live: TrackSummary;
  simulated: TrackSummary;
  runs: Run[];
}

export interface VolatilityView {
  model: VolatilityModel | null;
  assets: {
    symbol: string; company_name: string; sector: string; current_price: number;
    volatility: number | null; vol_forecast: number | null; vol_up_probability: number | null;
  }[];
  data_date?: string;
  horizon_days?: number;
}

export interface MarketItem {
  symbol: string;
  name: string;
  price: number;
  change_pct: number;
}
