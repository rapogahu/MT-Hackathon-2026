export interface ApiErrorDetail {
  code?: string;
  message?: string;
  fields?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields?: unknown;

  constructor(status: number, detail?: ApiErrorDetail | string) {
    const normalized = typeof detail === "string" ? { message: detail } : detail;
    super(normalized?.message ?? `Ошибка API (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.code = normalized?.code ?? "API_ERROR";
    this.fields = normalized?.fields;
  }
}

export function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error && error.name === "AbortError";
}

export function presentError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "FORECAST_NOT_LOADED" || error.status === 503) {
      return "Прогноз ещё не загружен. Повторите попытку позже.";
    }
    if (error.status === 404) {
      return "Выбранный выпуск прогноза не найден.";
    }
    return error.message;
  }

  if (error instanceof Error && !isAbortError(error)) {
    return error.message;
  }

  return "Не удалось получить данные прогноза.";
}
