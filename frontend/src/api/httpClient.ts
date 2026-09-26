import { ApiError, type ApiErrorDetail } from "./errors";
import type {
  AggregateResponse,
  DataRequest,
  DayResponse,
  ExportResult,
  ForecastDataClient,
  Granularity,
  PointResponse,
  ProductRoutesResponse,
  RouteFilter,
  RunMetadata,
  RunsResponse,
  TimeseriesResponse,
  MapRoutesResponse,
  ReferenceGeometryResponse,
  DirectionsResponse,
  StopsResponse,
  SegmentsResponse,
} from "./types";

interface HttpClientOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
}

export class HttpForecastClient implements ForecastDataClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor({ baseUrl, fetchImpl = fetch }: HttpClientOptions) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.fetchImpl = fetchImpl;
  }

  getRuns(options?: DataRequest): Promise<RunsResponse> {
    return this.request("/api/forecast/runs", options);
  }

  getRun(runId: string, options?: DataRequest): Promise<RunMetadata> {
    return this.request(`/api/forecast/runs/${encodeURIComponent(runId)}`, options);
  }

  getRoutes(runId: string, options?: DataRequest): Promise<ProductRoutesResponse> {
    return this.request(`/api/forecast/routes?run_id=${encodeURIComponent(runId)}`, options);
  }

  getDay(
    input: { runId: string; route: RouteFilter; date: string },
    options?: DataRequest,
  ): Promise<DayResponse> {
    const query = new URLSearchParams({ run_id: input.runId });
    if (input.route !== null) query.set("route", String(input.route));
    query.set("date", input.date);
    return this.request(`/api/forecast?${query.toString()}`, options);
  }

  getPoint(
    input: { runId: string; route: RouteFilter; date: string; hour: number },
    options?: DataRequest,
  ): Promise<PointResponse> {
    const query = new URLSearchParams({ run_id: input.runId });
    if (input.route !== null) query.set("route", String(input.route));
    query.set("date", input.date);
    query.set("hour", String(input.hour));
    return this.request(`/api/forecast/point?${query.toString()}`, options);
  }

  getTimeseries(
    input: { runId: string; route: RouteFilter; from: string; to: string },
    options?: DataRequest,
  ): Promise<TimeseriesResponse> {
    const query = this.rangeQuery(input);
    return this.request(`/api/timeseries?${query.toString()}`, options);
  }

  getAggregate(
    input: {
      runId: string;
      route: RouteFilter;
      from: string;
      to: string;
      granularity: Exclude<Granularity, "hour">;
    },
    options?: DataRequest,
  ): Promise<AggregateResponse> {
    const query = this.rangeQuery(input);
    query.set("granularity", input.granularity);
    return this.request(`/api/forecast/aggregate?${query.toString()}`, options);
  }

  async exportCsv(
    input: { runId: string; route: RouteFilter; from: string; to: string; hour?: number },
    options?: DataRequest,
  ): Promise<ExportResult> {
    const query = this.rangeQuery(input);
    if (input.hour !== undefined) query.set("hour", String(input.hour));
    const response = await this.fetchResponse(`/api/export.csv?${query.toString()}`, options, "text/csv");
    const disposition = response.headers.get("Content-Disposition") ?? "";
    const match = /filename\*?=(?:UTF-8''|\")?([^";]+)/i.exec(disposition);
    const proposed = match ? decodeURIComponent(match[1].trim()) : `forecast_${input.from}_${input.to}.csv`;
    const filename = proposed.replace(/[^\p{L}\p{N}._-]+/gu, "_");
    return { blob: await response.blob(), filename };
  }

  getMapRoutes(
    input: { runId: string; route: RouteFilter; date: string; hour: number },
    options?: DataRequest,
  ): Promise<MapRoutesResponse> {
    const query = new URLSearchParams({ run_id: input.runId, date: input.date, hour: String(input.hour) });
    if (input.route !== null) query.set("route", String(input.route));
    return this.request(`/api/map/routes?${query.toString()}`, options);
  }

  getReferenceGeometry(route: number, options?: DataRequest): Promise<ReferenceGeometryResponse> {
    return this.request(`/api/routes/number/${encodeURIComponent(route)}/geometry`, options);
  }

  getDirections(route: number, options?: DataRequest): Promise<DirectionsResponse> {
    return this.request(`/api/routes/number/${encodeURIComponent(route)}/directions`, options);
  }

  getStops(
    input: { route: number; tripId?: string; directionId?: number },
    options?: DataRequest,
  ): Promise<StopsResponse> {
    return this.request(`/api/routes/number/${encodeURIComponent(input.route)}/stops${this.navigationQuery(input)}`, options);
  }

  getSegments(
    input: { route: number; tripId?: string; directionId?: number },
    options?: DataRequest,
  ): Promise<SegmentsResponse> {
    return this.request(`/api/routes/number/${encodeURIComponent(input.route)}/segments${this.navigationQuery(input)}`, options);
  }

  private async request<T>(path: string, options?: DataRequest): Promise<T> {
    const response = await this.fetchResponse(path, options, "application/json");
    return (await response.json()) as T;
  }

  private rangeQuery(input: {
    runId: string;
    route: RouteFilter;
    from: string;
    to: string;
  }): URLSearchParams {
    const query = new URLSearchParams({ run_id: input.runId, from: input.from, to: input.to });
    if (input.route !== null) query.set("route", String(input.route));
    return query;
  }

  private navigationQuery(input: { tripId?: string; directionId?: number }): string {
    const query = new URLSearchParams();
    if (input.tripId !== undefined) query.set("trip_id", input.tripId);
    if (input.directionId !== undefined) query.set("direction_id", String(input.directionId));
    const value = query.toString();
    return value ? `?${value}` : "";
  }

  private async fetchResponse(
    path: string,
    options: DataRequest | undefined,
    accept: string,
  ): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        headers: { Accept: accept },
        signal: options?.signal,
      });
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        throw error;
      }
      throw new Error("API недоступен. Проверьте адрес сервиса и соединение.");
    }

    if (!response.ok) {
      let detail: ApiErrorDetail | string | undefined;
      try {
        const payload = (await response.json()) as { detail?: ApiErrorDetail | string };
        detail = payload.detail;
      } catch {
        detail = undefined;
      }
      throw new ApiError(response.status, detail);
    }
    return response;
  }
}
