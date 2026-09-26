import { ApiError } from "../api/errors";
import {
  COMPETITION_ROUTES,
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
} from "../api/types";

export type FixtureScenario = "default" | "empty-runs" | "error" | "degenerate";

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
    input: { runId: string; route: number; date: string },
    options?: DataRequest,
  ): Promise<DayResponse> {
    await this.pause(options?.signal);
    this.assertHealthy();
    this.assertRun(input.runId);
    this.assertRoute(input.route);
    assertDate(input.date);
    const points = Array.from({ length: 24 }, (_, hour) =>
      makeFixturePoint(input.route, input.date, hour, this.scenario === "degenerate"),
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
    input: { runId: string; route: number; date: string; hour: number },
    options?: DataRequest,
  ): Promise<PointResponse> {
    await this.pause(options?.signal);
    this.assertHealthy();
    this.assertRun(input.runId);
    this.assertRoute(input.route);
    assertDate(input.date);
    if (!Number.isInteger(input.hour) || input.hour < 0 || input.hour > 23) {
      throw new ApiError(422, { code: "INVALID_REQUEST", message: "Час должен быть от 0 до 23" });
    }
    const point = makeFixturePoint(
      input.route,
      input.date,
      input.hour,
      this.scenario === "degenerate",
    );
    return {
      run_id: input.runId,
      route: input.route,
      date: input.date,
      hour: input.hour,
      count: 1,
      points: [point],
    };
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
