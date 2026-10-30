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
  portfolio: { max_per_sector: number; weighting: string };
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
  /** Which registered model version produced this analysis (absent on analyses from before the registry) */
  model?: AnalysisModel;
}

export interface AnalysisModel {
  version: string | null;
  /** true: an existing (pinned) version was used; false: models were trained for this analysis */
  reused: boolean;
  registry: string | null;
  run_id?: string;
  error?: string;
}

export interface ModelVersion {
  version: string;
  created_at: string | null;
  run_id: string;
  run_name: string | null;
  status: string;
  champion: boolean;
  data_date: string | null;
  git_commit: string | null;
  params: Record<string, string>;
  metrics: Record<string, number>;
  run_url: string | null;
}

export interface ModelRegistryView {
  enabled: boolean;
  name?: string;
  tracking_uri?: string;
  ui_url?: string | null;
  champion: string | null;
  pinned: boolean;
  loaded_version?: string | null;
  versions: ModelVersion[];
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
  forecast?: (AssetForecast & { horizons: ForecastHorizon[]; base_date: string }) | null;
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

export type Severity = 'info' | 'warning' | 'critical';

export interface AppNotification {
  id: number;
  universe: Universe;
  type: 'unusual_move' | 'volume_spike' | 'gap' | 'market_move' | 'portfolio_change' | 'volatility_rising';
  severity: Severity;
  symbol: string | null;
  title: string;
  body: string;
  data: Record<string, unknown>;
  event_date: string;
  session: 'open' | 'close' | 'analysis' | null;
  created_at: string;
  read_at: string | null;
  read: boolean;
}

export interface UnreadCount {
  total: number;
  critical: number;
  warning: number;
  info: number;
}

export interface SignalSchedule {
  enabled: boolean;
  timezone: string;
  open: string;
  close: string;
  next: Record<Universe, { at: string; session: 'open' | 'close' }[]>;
}

export interface IcSummary {
  mean: number | null;
  t_stat: number | null;
  positive_share: number | null;
  periods: number;
}

export interface LogRow {
  date: string;
  symbol: string;
  sector: string | null;
  score: number;
  rank: number;
  picked: boolean;
  weight: number | null;
  ml_probability: number | null;
  technical_score: number | null;
  momentum_score: number | null;
  volume_score: number | null;
  future_return: number;
  universe_return: number;
  excess_return: number;
}

export interface BreakdownRow {
  group: string;
  count: number;
  ic: number | null;
  top_quintile_excess: number | null;
  top_quintile_hit_rate: number | null;
  picked_excess: number | null;
}

export interface PerformanceSource {
  source: 'live' | 'backtest';
  id: string | null;
  label: string;
  created_at?: string;
}

export interface PerformanceReport {
  source: 'live' | 'backtest';
  backtest_id: string | null;
  sources: PerformanceSource[];
  summary: {
    predictions: number; periods: number; assets?: number; start?: string; end?: string;
    ic?: IcSummary; decile_spread?: number | null; top_bucket_hit_rate?: number | null;
    picked_count?: number; picked_mean_excess?: number | null; picked_hit_rate?: number | null;
    overall_hit_rate?: number;
  };
  components: (IcSummary & { key: string; label: string; decile_spread: number | null })[];
  deciles: { buckets: { bucket: number; mean_excess: number; hit_rate: number; count: number }[];
    spread: number | null; monotonicity: number | null; bucket_count?: number };
  calibration: { bins: { predicted: number; observed: number; count: number }[]; brier: number | null };
  ic_series: { date: string; ic: number; rolling: number | null }[];
  breakdowns: { sector: BreakdownRow[]; regime: BreakdownRow[]; direction: BreakdownRow[] };
  log: LogRow[];
}

export interface ExperimentResult {
  headline: {
    ic_mean: number | null; ic_t_stat: number | null; decile_spread: number | null;
    picked_mean_excess: number | null; picked_hit_rate: number | null; periods: number | null;
    annualized_return: number | null; excess_t_stat: number | null; universe_annualized_return: number | null;
  };
  summary: PerformanceReport['summary'];
  components: PerformanceReport['components'];
  windows: { dev_start: string; dev_end: string; lockbox_start: string; lockbox_end: string };
}

export interface Experiment {
  id: string;
  universe: Universe;
  name: string;
  settings: Record<string, number | string | boolean>;
  top_n: number | null;
  status: 'queued' | 'running' | 'done' | 'failed';
  error: string | null;
  created_at: string;
  dev_backtest_id: string | null;
  lockbox_backtest_id: string | null;
  lockbox_checked_at: string | null;
  development: ExperimentResult | null;
  lockbox: ExperimentResult | null;
}

export interface SettingSpec {
  type: 'int' | 'float' | 'bool' | 'choice';
  min?: number;
  max?: number;
  choices?: string[];
  label: string;
}

export interface PriceRange {
  q05: number; q25: number; q50: number; q75: number; q95: number;
  days: number;
  sigma: number;
}

export interface RangeReliability {
  scored: number;
  coverage_50: number | null;
  coverage_90: number | null;
}

export interface ForecastHorizon { key: 'day' | 'week'; days: number; label: string }

export interface AssetForecast {
  symbol: string;
  name: string;
  sector: string | null;
  price: number;
  base_date: string;
  beat_probability: number | null;
  rank: number | null;
  picked: boolean;
  /** live: from this app's own forecasts; simulated: replayed on past dates (demo) */
  reliability_source: 'live' | 'simulated';
  reliability: Record<string, RangeReliability>;
  day?: PriceRange;
  week?: PriceRange;
}

export interface ForecastView {
  created_at: string;
  base_date: string;
  method: string;
  horizons: ForecastHorizon[];
  /** Coverage on held-out dates when the model was fitted */
  evaluation: Record<string, { coverage_50: number; coverage_90: number; samples: number; days: number;
    test_start: string; test_end: string }>;
  reliability: { live: Record<string, RangeReliability>; simulated: Record<string, RangeReliability> };
  assets: AssetForecast[];
}
