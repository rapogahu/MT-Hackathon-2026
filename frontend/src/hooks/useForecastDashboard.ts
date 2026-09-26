import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { presentError } from "../api/errors";
import { COMPETITION_ROUTES, type ForecastDataClient, type ForecastPoint, type ProductRoute, type RunMetadata } from "../api/types";

interface Selection {
  runId: string;
  route: number;
  date: string;
  hour: number;
}

interface DashboardState {
  phase: "loading" | "empty" | "ready" | "error";
  selection: Selection | null;
  metadata: RunMetadata | null;
  routes: ProductRoute[];
  dayPoints: ForecastPoint[];
  selectedPoint: ForecastPoint | null;
  dataLoading: boolean;
  error: string | null;
  notice: string | null;
}

const initialState: DashboardState = {
  phase: "loading",
  selection: null,
  metadata: null,
  routes: [],
  dayPoints: [],
  selectedPoint: null,
  dataLoading: false,
  error: null,
  notice: null,
};

function readUrlState() {
  const params = new URLSearchParams(window.location.search);
  return {
    runId: params.get("run"),
    route: params.has("route") ? Number(params.get("route")) : Number.NaN,
    date: params.get("date"),
    hour: params.has("hour") ? Number(params.get("hour")) : Number.NaN,
  };
}

function isValidHour(value: number): boolean {
  return Number.isInteger(value) && value >= 0 && value <= 23;
}

export function useForecastDashboard(client: ForecastDataClient) {
  const [state, setState] = useState(initialState);
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);
  const [dataAttempt, setDataAttempt] = useState(0);
  const requestSequence = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    setState((current) => ({ ...current, phase: "loading", error: null }));

    void (async () => {
      try {
        const runs = await client.getRuns({ signal: controller.signal });
        if (!runs.active_run_id) {
          setState((current) => ({ ...current, phase: "empty", error: null }));
          return;
        }

        const url = readUrlState();
        const requestedRunExists = url.runId && runs.runs.some((run) => run.run_id === url.runId);
        const runId = requestedRunExists ? url.runId! : runs.active_run_id;
        const notice = url.runId && !requestedRunExists
          ? "Указанный выпуск недоступен — открыт активный прогноз."
          : null;
        const [metadata, catalog] = await Promise.all([
          client.getRun(runId, { signal: controller.signal }),
          client.getRoutes(runId, { signal: controller.signal }),
        ]);
        const availableRoutes = catalog.routes.filter((route) => route.forecast_available);
        const requestedRoute = availableRoutes.some((route) => route.route === url.route)
          ? url.route
          : 1;
        const route = availableRoutes.some((item) => item.route === requestedRoute)
          ? requestedRoute
          : availableRoutes[0]?.route ?? 1;
        const date = url.date && url.date >= metadata.forecast_start && url.date <= metadata.forecast_end
          ? url.date
          : metadata.forecast_start;
        const hour = isValidHour(url.hour) ? url.hour : 8;

        setState((current) => ({
          ...current,
          phase: "ready",
          selection: { runId, route, date, hour },
          metadata,
          routes: catalog.routes,
          error: null,
          notice,
        }));
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") return;
        setState((current) => ({
          ...current,
          phase: "error",
          error: presentError(error),
        }));
      }
    })();

    return () => controller.abort();
  }, [client, bootstrapAttempt]);

  useEffect(() => {
    if (!state.selection || state.phase !== "ready") return;
    const controller = new AbortController();
    const requested = state.selection;
    const requestId = ++requestSequence.current;
    setState((current) => ({ ...current, dataLoading: true, error: null, selectedPoint: null }));

    void Promise.all([
      client.getDay(
        { runId: requested.runId, route: requested.route, date: requested.date },
        { signal: controller.signal },
      ),
      client.getPoint(
        {
          runId: requested.runId,
          route: requested.route,
          date: requested.date,
          hour: requested.hour,
        },
        { signal: controller.signal },
      ),
    ])
      .then(([day, point]) => {
        if (requestId !== requestSequence.current) return;
        if (day.run_id !== requested.runId || point.run_id !== requested.runId) {
          throw new Error("API вернул данные другого выпуска.");
        }
        if (day.count !== 24 || day.points.length !== 24) {
          throw new Error("DAY-ответ должен содержать ровно 24 точки.");
        }
        const selectedPoint = point.points[0];
        if (!selectedPoint) throw new Error("Точка выбранного часа отсутствует.");
        setState((current) => ({
          ...current,
          dayPoints: [...day.points].sort((a, b) => a.hour - b.hour),
          selectedPoint,
          dataLoading: false,
          error: null,
        }));
      })
      .catch((error: unknown) => {
        if (requestId !== requestSequence.current) return;
        if (error instanceof Error && error.name === "AbortError") return;
        setState((current) => ({
          ...current,
          dayPoints: [],
          selectedPoint: null,
          dataLoading: false,
          error: presentError(error),
        }));
      });

    return () => controller.abort();
  }, [client, state.phase, state.selection, dataAttempt]);

  useEffect(() => {
    if (!state.selection) return;
    const params = new URLSearchParams(window.location.search);
    params.set("run", state.selection.runId);
    params.set("route", String(state.selection.route));
    params.set("date", state.selection.date);
    params.set("hour", String(state.selection.hour));
    params.set("view", "DAY");
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, [state.selection]);

  const updateSelection = useCallback((patch: Partial<Omit<Selection, "runId">>) => {
    setState((current) => ({
      ...current,
      selection: current.selection ? { ...current.selection, ...patch } : null,
    }));
  }, []);

  const retry = useCallback(() => {
    if (state.phase === "error") setBootstrapAttempt((value) => value + 1);
    else setDataAttempt((value) => value + 1);
  }, [state.phase]);

  const route = useMemo(
    () => state.routes.find((item) => item.route === state.selection?.route) ?? null,
    [state.routes, state.selection?.route],
  );

  return {
    ...state,
    route,
    supportedRoutes: state.routes.length
      ? state.routes
      : COMPETITION_ROUTES.map((number) => ({
          route: number,
          name: `Трамвай ${number}`,
          gtfs_route_ids: [],
          geometry_available: false,
          forecast_available: false,
        })),
    updateSelection,
    retry,
  };
}
