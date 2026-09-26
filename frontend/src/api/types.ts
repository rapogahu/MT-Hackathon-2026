export const COMPETITION_ROUTES = [1, 5, 7, 11, 12, 17, 25, 26, 28, 50] as const;

export type CompetitionRoute = (typeof COMPETITION_ROUTES)[number];
export type Horizon = "day" | "month" | "year";
export type ForecastKind = "forecast" | "scenario";
export type LoadCategory = "very_low" | "low" | "medium" | "high" | "very_high";

export interface RunSummary {
  run_id: string;
  profile: string;
  horizon: Horizon;
  forecast_kind: ForecastKind;
  training_end: string | null;
  forecast_start: string;
  forecast_end: string;
  routes: number[];
  row_count: number;
  imported_at: string;
  generated_at: string | null;
  model_version: string | null;
  timezone: string;
}

export interface NormalizationMetadata {
  route: number;
  source_type: "actuals" | "forecast";
  actual_batch_id: string | null;
  period_start: string;
  period_end: string;
  sample_count: number;
  q05: number;
  q95: number;
  degenerate: boolean;
  fallback_reason: string | null;
  algorithm_version: string;
}

export interface RunMetadata extends RunSummary {
  source_checksum: string;
  actual_batch_id: string | null;
  normalization_version: string;
  normalization: NormalizationMetadata[];
  evaluation_ids: string[];
  scenario_assumptions: string[] | null;
}

export interface RunsResponse {
  active_run_id: string | null;
  active_runs: Record<Horizon, string | null>;
  runs: RunSummary[];
}

export interface ProductRoute {
  route: number;
  name: string;
  gtfs_route_ids: string[];
  geometry_available: boolean;
  forecast_available: boolean;
}

export interface ProductRoutesResponse {
  run_id: string | null;
  count: number;
  routes: ProductRoute[];
}

export interface ForecastPoint {
  route: number;
  date: string;
  hour: number;
  prediction: number;
  relative_load: number;
  relative_load_pct: number;
  load_index: number;
  load_category: LoadCategory;
  normalization_degenerate: boolean;
}

export interface DayResponse {
  run_id: string;
  route: number | null;
  date: string;
  count: number;
  points: ForecastPoint[];
}

export interface PointResponse {
  run_id: string;
  route: number | null;
  date: string;
  hour: number;
  count: number;
  points: ForecastPoint[];
}

export interface DataRequest {
  signal?: AbortSignal;
}

export interface ForecastDataClient {
  getRuns(options?: DataRequest): Promise<RunsResponse>;
  getRun(runId: string, options?: DataRequest): Promise<RunMetadata>;
  getRoutes(runId: string, options?: DataRequest): Promise<ProductRoutesResponse>;
  getDay(
    input: { runId: string; route: number; date: string },
    options?: DataRequest,
  ): Promise<DayResponse>;
  getPoint(
    input: { runId: string; route: number; date: string; hour: number },
    options?: DataRequest,
  ): Promise<PointResponse>;
}
