import { ApiError, isAbortError, type ApiErrorDetail } from "./errors";
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
  RouteDirection,
  RouteStop,
} from "./types";

interface HttpClientOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
}

export class HttpForecastClient implements ForecastDataClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor({ baseUrl, fetchImpl }: HttpClientOptions) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.fetchImpl = fetchImpl ?? ((input, init) => globalThis.fetch(input, init));
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
    return this.request(`/api/forecast/timeseries?${query.toString()}`, options);
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

  async getDirections(route: number, options?: DataRequest): Promise<DirectionsResponse> {
    const payload = await this.request<DirectionsResponse | LegacyDirectionsResponse>(`/api/routes/number/${encodeURIComponent(route)}/directions`, options);
    if ("reference_version" in payload) return payload;
    const directions: RouteDirection[] = (payload.directions ?? []).map((item) => ({ geometry_id: geometryId(route, item.trip_id, item.direction_id), trip_id: String(item.trip_id), direction_id: Number(item.direction_id), valid_from: item.valid_from ?? "", valid_to: item.valid_to ?? null }));
    return { route, reference_version: legacyReference(payload.route_id ?? route), count: directions.length, directions };
  }

  async getStops(
    input: { route: number; tripId?: string; directionId?: number },
    options?: DataRequest,
  ): Promise<StopsResponse> {
    const payload = await this.request<StopsResponse | LegacyStopsResponse>(`/api/routes/number/${encodeURIComponent(input.route)}/stops${this.navigationQuery(input)}`, options);
    if ("reference_version" in payload) return payload;
    const rows = Object.values(payload.directions ?? {}).flat().filter((item) => (input.tripId === undefined || String(item.trip_id) === input.tripId) && (input.directionId === undefined || Number(item.direction_id) === input.directionId));
    const stops: RouteStop[] = rows.map((item) => ({ route: input.route, route_id: String(item.route_id), trip_id: String(item.trip_id), direction_id: Number(item.direction_id), geometry_id: geometryId(input.route, item.trip_id, item.direction_id), stop_sequence: Number(item.stop_sequence), stop_id: String(item.stop_id), stop_name: String(item.stop_name), lat: Number(item.stop_lat), lon: Number(item.stop_lon) }));
    return { route: input.route, reference_version: legacyReference(payload.route?.route_id ?? input.route), count: stops.length, stops };
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
      if (isAbortError(error)) {
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

interface LegacyDirection { trip_id: string | number; direction_id: string | number; valid_from?: string; valid_to?: string | null }
interface LegacyDirectionsResponse { route?: number; route_id?: string | number; directions?: LegacyDirection[] }
interface LegacyStop extends LegacyDirection { route_id: string | number; stop_sequence: string | number; stop_id: string | number; stop_name: string; stop_lat: number; stop_lon: number }
interface LegacyStopsResponse { route?: { route_id: string | number }; directions?: Record<string, LegacyStop[]> }
function geometryId(route: number, tripId: string | number, directionId: string | number) { return `route-${route}-${tripId}-${directionId}`; }
function legacyReference(routeId: string | number) { return `legacy-gtfs-${routeId}`; }
