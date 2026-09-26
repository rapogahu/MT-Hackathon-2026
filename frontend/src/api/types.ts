export const COMPETITION_ROUTES = [1, 5, 7, 11, 12, 17, 25, 26, 28, 50] as const;

export type CompetitionRoute = (typeof COMPETITION_ROUTES)[number];
export type Horizon = "day" | "month" | "year";
export type ForecastKind = "forecast" | "scenario";
export type LoadCategory = "very_low" | "low" | "medium" | "high" | "very_high";
export type RouteFilter = number | null;
export type ViewMode = "DAY" | "MONTH" | "PERIOD";
export type Granularity = "hour" | "day" | "week" | "month";

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

export interface TimeseriesResponse {
  run_id: string;
  route: RouteFilter;
  from: string;
  to: string;
  count: number;
  points: ForecastPoint[];
}

export interface AggregatePoint {
  route: number;
  date: string;
  period_start: string;
  period_end: string;
  prediction: number;
  hours_count: number;
  expected_hours: number;
  is_partial: boolean;
}

export interface AggregateResponse {
  run_id: string;
  route: RouteFilter;
  from: string;
  to: string;
  granularity: Exclude<Granularity, "hour">;
  count: number;
  points: AggregatePoint[];
}

export interface ExportResult {
  blob: Blob;
  filename: string;
}

export type Position = [number, number];

export interface LineStringGeometry {
  type: "LineString";
  coordinates: Position[];
}

export interface PointGeometry {
  type: "Point";
  coordinates: Position;
}

export interface GeoFeature<G, P> {
  type: "Feature";
  id?: string;
  geometry: G;
  properties: P;
}

export interface RouteGeometryProperties extends ForecastPoint {
  route_id: string;
  trip_id: string;
  direction_id: number;
  geometry_id: string;
  valid_from: string;
  valid_to: string | null;
  reference_actual_date: string;
  geometry_source: "stop_sequence";
  outside_validity_period: boolean;
}

export interface ReferenceGeometryProperties {
  route: number;
  route_id: string;
  trip_id: string;
  direction_id: number;
  geometry_id: string;
  valid_from: string;
  valid_to: string | null;
  reference_actual_date: string;
  geometry_source: "stop_sequence";
}

export interface FeatureCollection<P> {
  type: "FeatureCollection";
  features: Array<GeoFeature<LineStringGeometry, P>>;
}

export interface MapRoutesResponse extends FeatureCollection<RouteGeometryProperties> {
  run_id: string;
  date: string;
  hour: number;
  reference_version: string;
  geometry_mode: "reference";
}

export interface ReferenceGeometryResponse extends FeatureCollection<ReferenceGeometryProperties> {
  route: number;
  reference_version: string;
  geometry_available: boolean;
  geometry_mode: "reference";
}

export interface RouteDirection {
  geometry_id: string;
  trip_id: string;
  direction_id: number;
  valid_from: string;
  valid_to: string | null;
}

export interface DirectionsResponse {
  route: number;
  reference_version: string;
  count: number;
  directions: RouteDirection[];
}

export interface RouteStop {
  route: number;
  route_id: string;
  trip_id: string;
  direction_id: number;
  geometry_id: string;
  stop_sequence: number;
  stop_id: string;
  stop_name: string;
  lat: number;
  lon: number;
}

export interface StopsResponse {
  route: number;
  reference_version: string;
  count: number;
  stops: RouteStop[];
}

export interface RouteSegment {
  segment_id: string;
  geometry_id: string;
  route: number;
  trip_id: string;
  direction_id: number;
  from_stop_id: string;
  to_stop_id: string;
  from_sequence: number;
  to_sequence: number;
  from_stop_name: string;
  to_stop_name: string;
  geometry: LineStringGeometry;
}

export interface SegmentsResponse {
  route: number;
  reference_version: string;
  count: number;
  segments: RouteSegment[];
}

export interface DataRequest {
  signal?: AbortSignal;
}

export interface ForecastDataClient {
  getRuns(options?: DataRequest): Promise<RunsResponse>;
  getRun(runId: string, options?: DataRequest): Promise<RunMetadata>;
  getRoutes(runId: string, options?: DataRequest): Promise<ProductRoutesResponse>;
  getDay(
    input: { runId: string; route: RouteFilter; date: string },
    options?: DataRequest,
  ): Promise<DayResponse>;
  getPoint(
    input: { runId: string; route: RouteFilter; date: string; hour: number },
    options?: DataRequest,
  ): Promise<PointResponse>;
  getTimeseries(
    input: { runId: string; route: RouteFilter; from: string; to: string },
    options?: DataRequest,
  ): Promise<TimeseriesResponse>;
  getAggregate(
    input: {
      runId: string;
      route: RouteFilter;
      from: string;
      to: string;
      granularity: Exclude<Granularity, "hour">;
    },
    options?: DataRequest,
  ): Promise<AggregateResponse>;
  exportCsv(
    input: { runId: string; route: RouteFilter; from: string; to: string; hour?: number },
    options?: DataRequest,
  ): Promise<ExportResult>;
  getMapRoutes(
    input: { runId: string; route: RouteFilter; date: string; hour: number },
    options?: DataRequest,
  ): Promise<MapRoutesResponse>;
  getReferenceGeometry(route: number, options?: DataRequest): Promise<ReferenceGeometryResponse>;
  getDirections(route: number, options?: DataRequest): Promise<DirectionsResponse>;
  getStops(
    input: { route: number; tripId?: string; directionId?: number },
    options?: DataRequest,
  ): Promise<StopsResponse>;
  getSegments(
    input: { route: number; tripId?: string; directionId?: number },
    options?: DataRequest,
  ): Promise<SegmentsResponse>;
}
