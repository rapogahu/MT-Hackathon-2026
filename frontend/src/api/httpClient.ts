import { ApiError, type ApiErrorDetail } from "./errors";
import type {
  DataRequest,
  DayResponse,
  ForecastDataClient,
  PointResponse,
  ProductRoutesResponse,
  RunMetadata,
  RunsResponse,
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
    input: { runId: string; route: number; date: string },
    options?: DataRequest,
  ): Promise<DayResponse> {
    const query = new URLSearchParams({
      run_id: input.runId,
      route: String(input.route),
      date: input.date,
    });
    return this.request(`/api/forecast?${query.toString()}`, options);
  }

  getPoint(
    input: { runId: string; route: number; date: string; hour: number },
    options?: DataRequest,
  ): Promise<PointResponse> {
    const query = new URLSearchParams({
      run_id: input.runId,
      route: String(input.route),
      date: input.date,
      hour: String(input.hour),
    });
    return this.request(`/api/forecast/point?${query.toString()}`, options);
  }

  private async request<T>(path: string, options?: DataRequest): Promise<T> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        headers: { Accept: "application/json" },
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

    return (await response.json()) as T;
  }
}
