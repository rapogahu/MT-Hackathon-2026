import { ApiError } from "../api/errors";
import {
  COMPETITION_ROUTES,
  type AggregatePoint,
  type AggregateResponse,
  type DataRequest,
  type DayResponse,
  type ForecastDataClient,
  type ForecastPoint,
  type LoadCategory,
  type PointResponse,
  type ProductRoute,
  type ProductRoutesResponse,
  type RunMetadata,
  type RunsResponse,
  type RunSummary,
  type RouteFilter,
  type TimeseriesResponse,
  type ExportResult,
  type DirectionsResponse,
  type MapRoutesResponse,
  type ReferenceGeometryResponse,
  type SegmentsResponse,
  type StopsResponse,
} from "../api/types";
import { addDays, enumerateDates, parseIsoDate } from "../api/dateUtils";
import { fixturePaths, REFERENCE_VERSION } from "./referenceFixture";

export type FixtureScenario = "default" | "empty-runs" | "error" | "degenerate" | "map-error";

export const FIXTURE_RUN_ID = "6ce61394-dd47-4f27-a430-b215e52bbf09";
export const FIXTURE_START = "2025-11-01";
export const FIXTURE_END = "2025-12-31";

interface FixtureClientOptions {
  scenario?: FixtureScenario;
  latencyMs?: number;
}

const runSummary: RunSummary = {
  run_id: FIXTURE_RUN_ID,
  profile: "competition",
  horizon: "month",
  forecast_kind: "forecast",
  training_end: "2025-10-31",
  forecast_start: FIXTURE_START,
  forecast_end: FIXTURE_END,
  routes: [...COMPETITION_ROUTES],
  row_count: 14_640,
  imported_at: "2025-10-31T21:20:00+03:00",
  generated_at: "2025-10-31T20:45:00+03:00",
  model_version: "fixture-ui-1",
  timezone: "Europe/Moscow",
};

const routeRecords: ProductRoute[] = COMPETITION_ROUTES.map((route) => ({
  route,
  name: `Трамвай ${route}`,
  gtfs_route_ids: [1, 5, 7, 11, 12].includes(route) ? [`fixture-${route}`] : [],
  geometry_available: [1, 5, 7, 11, 12].includes(route),
  forecast_available: true,
}));

function indexToCategory(index: number): LoadCategory {
  if (index <= 2) return "very_low";
  if (index <= 4) return "low";
  if (index <= 6) return "medium";
  if (index <= 8) return "high";
  return "very_high";
}

function isoDayNumber(date: string): number {
  const [, month, day] = date.split("-").map(Number);
  return (month - 11) * 30 + day;
}

export function makeFixturePoint(
  route: number,
  date: string,
  hour: number,
  forceDegenerate = false,
): ForecastPoint {
  const day = isoDayNumber(date);
  const routeOffset = COMPETITION_ROUTES.indexOf(route as (typeof COMPETITION_ROUTES)[number]);
  const commutePeak =
    220 * Math.exp(-Math.pow(hour - 8, 2) / 8) +
    260 * Math.exp(-Math.pow(hour - 18, 2) / 10);
  const nightFactor = hour < 5 ? 0.08 : 1;
  const weeklyWave = 35 * Math.sin((day / 7) * Math.PI * 2 + routeOffset * 0.31);
  let prediction = Math.max(
    0,
    Math.round((115 + routeOffset * 19 + commutePeak + weeklyWave) * nightFactor),
  );

  if (route === 5 && hour === 3 && day % 5 === 1) {
    prediction = 0;
  }

  const degenerate = forceDegenerate || route === 17;
  const relativeLoad = degenerate ? 0.5 : Math.min(1, Math.max(0, prediction / 620));
  const relativeLoadPct = degenerate ? 50 : Math.floor(relativeLoad * 100 + 0.5);
  const loadIndex = degenerate
    ? 5
    : Math.min(10, Math.max(1, Math.floor(relativeLoad * 10) + 1));

  return {
    route,
    date,
    hour,
    prediction,
    relative_load: relativeLoad,
    relative_load_pct: relativeLoadPct,
    load_index: loadIndex,
    load_category: indexToCategory(loadIndex),
    normalization_degenerate: degenerate,
  };
}

function assertDate(date: string): void {
  if (date < FIXTURE_START || date > FIXTURE_END) {
    throw new ApiError(422, {
      code: "OUTSIDE_FORECAST_RANGE",
      message: `Допустимый диапазон: ${FIXTURE_START} — ${FIXTURE_END}`,
    });
  }
}

export class FixtureForecastClient implements ForecastDataClient {
  private readonly scenario: FixtureScenario;
  private readonly latencyMs: number;

  constructor({ scenario = "default", latencyMs = 90 }: FixtureClientOptions = {}) {
    this.scenario = scenario;
    this.latencyMs = latencyMs;
  }

  async getRuns(options?: DataRequest): Promise<RunsResponse> {
    await this.pause(options?.signal);
    this.assertHealthy();
    if (this.scenario === "empty-runs") {
      return {
        active_run_id: null,
        active_runs: { day: null, month: null, year: null },
        runs: [],
      };
    }
    return {
      active_run_id: FIXTURE_RUN_ID,
      active_runs: { day: null, month: FIXTURE_RUN_ID, year: null },
      runs: [{ ...runSummary }],
    };
  }

  async getRun(runId: string, options?: DataRequest): Promise<RunMetadata> {
    await this.pause(options?.signal);
    this.assertHealthy();
    this.assertRun(runId);
    return {
      ...runSummary,
      source_checksum: "fixture-only-not-a-model-forecast",
      actual_batch_id: null,
      normalization_version: "fixture-v1",
      normalization: COMPETITION_ROUTES.map((route) => ({
        route,
        source_type: "forecast" as const,
        actual_batch_id: null,
        period_start: FIXTURE_START,
        period_end: FIXTURE_END,
        sample_count: 1_464,
        q05: route === 17 || this.scenario === "degenerate" ? 50 : 12,
        q95: route === 17 || this.scenario === "degenerate" ? 50 : 620,
        degenerate: route === 17 || this.scenario === "degenerate",
        fallback_reason:
          route === 17 || this.scenario === "degenerate"
            ? "fixture_degenerate_scale"
            : "fixture_has_no_actuals",
        algorithm_version: "fixture-v1",
      })),
      evaluation_ids: [],
      scenario_assumptions: null,
    };
  }

  async getRoutes(runId: string, options?: DataRequest): Promise<ProductRoutesResponse> {
    await this.pause(options?.signal);
    this.assertHealthy();
    this.assertRun(runId);
    return { run_id: runId, count: routeRecords.length, routes: routeRecords.map((route) => ({ ...route })) };
  }

  async getDay(
    input: { runId: string; route: RouteFilter; date: string },
    options?: DataRequest,
  ): Promise<DayResponse> {
    await this.pause(options?.signal);
    this.assertHealthy();
    this.assertRun(input.runId);
    this.assertRouteFilter(input.route);
    assertDate(input.date);
    const points = this.routesFor(input.route).flatMap((route) =>
      Array.from({ length: 24 }, (_, hour) =>
        makeFixturePoint(route, input.date, hour, this.scenario === "degenerate"),
      ),
    );
    return {
      run_id: input.runId,
      route: input.route,
      date: input.date,
      count: points.length,
      points,
    };
  }

  async getPoint(
    input: { runId: string; route: RouteFilter; date: string; hour: number },
    options?: DataRequest,
  ): Promise<PointResponse> {
    await this.pause(options?.signal);
    this.assertHealthy();
    this.assertRun(input.runId);
    this.assertRouteFilter(input.route);
    assertDate(input.date);
    if (!Number.isInteger(input.hour) || input.hour < 0 || input.hour > 23) {
      throw new ApiError(422, { code: "INVALID_REQUEST", message: "Час должен быть от 0 до 23" });
    }
    const points = this.routesFor(input.route).map((route) =>
      makeFixturePoint(route, input.date, input.hour, this.scenario === "degenerate"),
    );
    return {
      run_id: input.runId,
      route: input.route,
      date: input.date,
      hour: input.hour,
      count: points.length,
      points,
    };
  }

  async getTimeseries(
    input: { runId: string; route: RouteFilter; from: string; to: string },
    options?: DataRequest,
  ): Promise<TimeseriesResponse> {
    await this.pause(options?.signal);
    this.assertHealthy();
    this.assertRun(input.runId);
    this.assertRouteFilter(input.route);
    this.assertRange(input.from, input.to);
    const points = enumerateDates(input.from, input.to).flatMap((date) =>
      this.routesFor(input.route).flatMap((route) =>
        Array.from({ length: 24 }, (_, hour) =>
          makeFixturePoint(route, date, hour, this.scenario === "degenerate"),
        ),
      ),
    );
    return { run_id: input.runId, route: input.route, from: input.from, to: input.to, count: points.length, points };
  }

  async getAggregate(
    input: { runId: string; route: RouteFilter; from: string; to: string; granularity: "day" | "week" | "month" },
    options?: DataRequest,
  ): Promise<AggregateResponse> {
    const series = await this.getTimeseries(input, options);
    const groups = new Map<string, { route: number; date: string; start: string; end: string; fullStart: string; fullEnd: string; prediction: number; hours: number }>();
    for (const point of series.points) {
      const bucket = bucketFor(point.date, input.granularity);
      const key = `${point.route}:${bucket.date}`;
      const current = groups.get(key) ?? { route: point.route, date: bucket.date, start: point.date, end: point.date, fullStart: bucket.start, fullEnd: bucket.end, prediction: 0, hours: 0 };
      current.start = current.start < point.date ? current.start : point.date;
      current.end = current.end > point.date ? current.end : point.date;
      current.prediction += point.prediction;
      current.hours += 1;
      groups.set(key, current);
    }
    const points: AggregatePoint[] = [...groups.values()].map((item) => ({
      route: item.route,
      date: item.date,
      period_start: item.start,
      period_end: item.end,
      prediction: item.prediction,
      hours_count: item.hours,
      expected_hours: enumerateDates(item.start, item.end).length * 24,
      is_partial: item.start !== item.fullStart || item.end !== item.fullEnd,
    })).sort((a, b) => a.route - b.route || a.date.localeCompare(b.date));
    return { run_id: input.runId, route: input.route, from: input.from, to: input.to, granularity: input.granularity, count: points.length, points };
  }

  async exportCsv(
    input: { runId: string; route: RouteFilter; from: string; to: string; hour?: number },
    options?: DataRequest,
  ): Promise<ExportResult> {
    const series = await this.getTimeseries(input, options);
    const points = input.hour === undefined ? series.points : series.points.filter((point) => point.hour === input.hour);
    const rows = ["route;date;hour;prediction;relative_load_pct;load_index;load_category", ...points.map((point) =>
      [point.route, point.date, point.hour, point.prediction, point.relative_load_pct, point.load_index, point.load_category].join(";"),
    )];
    return { blob: new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8" }), filename: `forecast_${input.from}_${input.to}.csv` };
  }

  async getMapRoutes(
    input: { runId: string; route: RouteFilter; date: string; hour: number },
    options?: DataRequest,
  ): Promise<MapRoutesResponse> {
    await this.pause(options?.signal); this.assertHealthy();
    if (this.scenario === "map-error") throw new ApiError(503, { code: "MAP_UNAVAILABLE", message: "Тестовая ошибка географического блока" });
    this.assertRun(input.runId); this.assertRouteFilter(input.route); assertDate(input.date);
    const routes = this.routesFor(input.route);
    const features = fixturePaths.filter((path) => routes.includes(path.properties.route)).map((path) => {
      const point = makeFixturePoint(path.properties.route, input.date, input.hour, this.scenario === "degenerate");
      return { type: "Feature" as const, id: path.properties.geometry_id, geometry: { type: "LineString" as const, coordinates: path.coordinates }, properties: { ...point, ...path.properties, outside_validity_period: input.date < path.properties.valid_from || (path.properties.valid_to !== null && input.date > path.properties.valid_to) } };
    });
    return { type: "FeatureCollection", features, run_id: input.runId, date: input.date, hour: input.hour, reference_version: REFERENCE_VERSION, geometry_mode: "reference" };
  }

  async getReferenceGeometry(route: number, options?: DataRequest): Promise<ReferenceGeometryResponse> {
    await this.pause(options?.signal); this.assertHealthy(); this.assertRoute(route);
    const features = fixturePaths.filter((path) => path.properties.route === route).map((path) => ({ type: "Feature" as const, id: path.properties.geometry_id, geometry: { type: "LineString" as const, coordinates: path.coordinates }, properties: path.properties }));
    return { type: "FeatureCollection", features, route, reference_version: REFERENCE_VERSION, geometry_available: features.length > 0, geometry_mode: "reference" };
  }

  async getDirections(route: number, options?: DataRequest): Promise<DirectionsResponse> {
    await this.pause(options?.signal); this.assertHealthy(); this.assertRoute(route);
    const directions = fixturePaths.filter((path) => path.properties.route === route).map((path) => path.direction);
    return { route, reference_version: REFERENCE_VERSION, count: directions.length, directions };
  }

  async getStops(input: { route: number; tripId?: string; directionId?: number }, options?: DataRequest): Promise<StopsResponse> {
    await this.pause(options?.signal); this.assertHealthy(); this.assertRoute(input.route);
    const stops = this.navigationPaths(input).flatMap((path) => path.stops);
    return { route: input.route, reference_version: REFERENCE_VERSION, count: stops.length, stops };
  }

  async getSegments(input: { route: number; tripId?: string; directionId?: number }, options?: DataRequest): Promise<SegmentsResponse> {
    await this.pause(options?.signal); this.assertHealthy(); this.assertRoute(input.route);
    const segments = this.navigationPaths(input).flatMap((path) => path.segments);
    return { route: input.route, reference_version: REFERENCE_VERSION, count: segments.length, segments };
  }

  private assertHealthy(): void {
    if (this.scenario === "error") {
      throw new ApiError(503, {
        code: "FORECAST_NOT_LOADED",
        message: "Тестовый сценарий недоступности прогноза",
      });
    }
  }

  private assertRun(runId: string): void {
    if (runId !== FIXTURE_RUN_ID) {
      throw new ApiError(404, { code: "RUN_NOT_FOUND", message: "Выпуск не найден" });
    }
  }

  private assertRoute(route: number): void {
    if (!COMPETITION_ROUTES.includes(route as (typeof COMPETITION_ROUTES)[number])) {
      throw new ApiError(422, { code: "UNSUPPORTED_ROUTE", message: "Маршрут не поддерживается" });
    }
  }

  private assertRouteFilter(route: RouteFilter): void {
    if (route !== null) this.assertRoute(route);
  }

  private routesFor(route: RouteFilter): readonly number[] {
    return route === null ? COMPETITION_ROUTES : [route];
  }

  private assertRange(from: string, to: string): void {
    assertDate(from);
    assertDate(to);
    if (from > to) throw new ApiError(422, { code: "INVALID_REQUEST", message: "Начало периода позже окончания" });
  }

  private navigationPaths(input: { route: number; tripId?: string; directionId?: number }) {
    return fixturePaths.filter((path) => path.properties.route === input.route && (input.tripId === undefined || path.properties.trip_id === input.tripId) && (input.directionId === undefined || path.properties.direction_id === input.directionId));
  }

  private pause(signal?: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(new DOMException("Aborted", "AbortError"));
        return;
      }
      const timer = window.setTimeout(resolve, this.latencyMs);
      signal?.addEventListener(
        "abort",
        () => {
          window.clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        },
        { once: true },
      );
    });
  }
}

function bucketFor(date: string, granularity: "day" | "week" | "month") {
  if (granularity === "day") return { date, start: date, end: date };
  if (granularity === "month") {
    const month = date.slice(0, 7);
    const [year, number] = month.split("-").map(Number);
    const end = new Date(Date.UTC(year, number, 0, 12)).toISOString().slice(0, 10);
    return { date: `${month}-01`, start: `${month}-01`, end };
  }
  const weekday = parseIsoDate(date).getUTCDay() || 7;
  const start = addDays(date, 1 - weekday);
  return { date: start, start, end: addDays(start, 6) };
}
