import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clampRange, monthBounds } from "../api/dateUtils";
import { presentError } from "../api/errors";
import { COMPETITION_ROUTES, type AggregatePoint, type ForecastDataClient, type ForecastPoint, type Granularity, type ProductRoute, type RouteFilter, type RunMetadata, type ViewMode } from "../api/types";

export interface Selection { runId: string; route: RouteFilter; view: ViewMode; date: string; hour: number; month: string; from: string; to: string; granularity: Granularity }
const validHour = (value: number) => Number.isInteger(value) && value >= 0 && value <= 23;
const validView = (value: string | null): value is ViewMode => value === "DAY" || value === "MONTH" || value === "PERIOD";
const validGranularity = (value: string | null): value is Granularity => value === "hour" || value === "day" || value === "week" || value === "month";

export function useForecastDashboard(client: ForecastDataClient) {
  const [phase, setPhase] = useState<"loading" | "empty" | "ready" | "error">("loading");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [metadata, setMetadata] = useState<RunMetadata | null>(null);
  const [routes, setRoutes] = useState<ProductRoute[]>([]);
  const [forecastPoints, setForecastPoints] = useState<ForecastPoint[]>([]);
  const [aggregatePoints, setAggregatePoints] = useState<AggregatePoint[]>([]);
  const [pointRows, setPointRows] = useState<ForecastPoint[]>([]);
  const [draftFrom, setDraftFrom] = useState(""); const [draftTo, setDraftTo] = useState("");
  const [dataLoading, setDataLoading] = useState(false); const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false); const [exportMessage, setExportMessage] = useState<string | null>(null); const [attempt, setAttempt] = useState(0); const sequence = useRef(0);

  useEffect(() => {
    const controller = new AbortController(); setPhase("loading"); setError(null);
    void (async () => {
      try {
        const runs = await client.getRuns({ signal: controller.signal });
        if (!runs.active_run_id) { setPhase("empty"); return; }
        const params = new URLSearchParams(window.location.search); const askedRun = params.get("run");
        const runId = askedRun && runs.runs.some((run) => run.run_id === askedRun) ? askedRun : runs.active_run_id;
        const [meta, catalog] = await Promise.all([client.getRun(runId, { signal: controller.signal }), client.getRoutes(runId, { signal: controller.signal })]);
        const routeParam = params.get("route"); const parsedRoute = routeParam === "ALL" ? null : routeParam ? Number(routeParam) : 1;
        const route: RouteFilter = parsedRoute === null || catalog.routes.some((item) => item.forecast_available && item.route === parsedRoute) ? parsedRoute : (catalog.routes.find((item) => item.forecast_available)?.route ?? 1);
        const dateParam = params.get("date"); const date = dateParam && dateParam >= meta.forecast_start && dateParam <= meta.forecast_end ? dateParam : meta.forecast_start;
        const hourValue = params.get("hour"); const hourParam = hourValue === null ? Number.NaN : Number(hourValue); const hour = validHour(hourParam) ? hourParam : 8;
        const viewValue = params.get("view"); const view = validView(viewValue) ? viewValue : "DAY";
        const monthParam = params.get("month"); const month = monthParam && /^\d{4}-\d{2}$/.test(monthParam) && monthParam >= meta.forecast_start.slice(0, 7) && monthParam <= meta.forecast_end.slice(0, 7) ? monthParam : date.slice(0, 7);
        const fromParam = params.get("from"); const toParam = params.get("to"); const from = fromParam && fromParam >= meta.forecast_start && fromParam <= meta.forecast_end ? fromParam : meta.forecast_start; const to = toParam && toParam >= from && toParam <= meta.forecast_end ? toParam : meta.forecast_end;
        const granularityValue = params.get("granularity"); const granularity = validGranularity(granularityValue) ? granularityValue : "day";
        setMetadata(meta); setRoutes(catalog.routes); setSelection({ runId, route, view, date, hour, month, from, to, granularity }); setDraftFrom(from); setDraftTo(to); setNotice(askedRun && askedRun !== runId ? "Указанный выпуск недоступен — открыт активный прогноз." : null); setPhase("ready");
      } catch (cause) { if (cause instanceof Error && cause.name === "AbortError") return; setError(presentError(cause)); setPhase("error"); }
    })();
    return () => controller.abort();
  }, [client, attempt]);

  useEffect(() => {
    if (!selection || !metadata || phase !== "ready") return;
    const controller = new AbortController(); const id = ++sequence.current; setDataLoading(true); setError(null); setForecastPoints([]); setAggregatePoints([]);
    const pointRequest = client.getPoint({ runId: selection.runId, route: selection.route, date: selection.date, hour: selection.hour }, { signal: controller.signal });
    let dataRequest: Promise<{ forecast: ForecastPoint[]; aggregate: AggregatePoint[] }>;
    if (selection.view === "DAY") dataRequest = client.getDay({ runId: selection.runId, route: selection.route, date: selection.date }, { signal: controller.signal }).then((value) => ({ forecast: value.points, aggregate: [] }));
    else {
      const month = monthBounds(selection.month); const range = selection.view === "MONTH" ? clampRange(month.from, month.to, metadata.forecast_start, metadata.forecast_end) : { from: selection.from, to: selection.to };
      dataRequest = selection.view === "PERIOD" && selection.granularity === "hour" ? client.getTimeseries({ runId: selection.runId, route: selection.route, ...range }, { signal: controller.signal }).then((value) => ({ forecast: value.points, aggregate: [] })) : client.getAggregate({ runId: selection.runId, route: selection.route, ...range, granularity: selection.view === "MONTH" ? "day" : selection.granularity as "day" | "week" | "month" }, { signal: controller.signal }).then((value) => ({ forecast: [], aggregate: value.points }));
    }
    void Promise.all([pointRequest, dataRequest]).then(([point, data]) => { if (id !== sequence.current) return; setPointRows(point.points); setForecastPoints(data.forecast); setAggregatePoints(data.aggregate); setDataLoading(false); }).catch((cause) => { if (id !== sequence.current || (cause instanceof Error && cause.name === "AbortError")) return; setPointRows([]); setForecastPoints([]); setAggregatePoints([]); setDataLoading(false); setError(presentError(cause)); });
    return () => controller.abort();
  }, [client, selection, metadata, phase, attempt]);

  useEffect(() => { if (!selection) return; const params = new URLSearchParams(window.location.search); const values = { run: selection.runId, route: selection.route === null ? "ALL" : String(selection.route), view: selection.view, date: selection.date, hour: String(selection.hour), month: selection.month, from: selection.from, to: selection.to, granularity: selection.granularity }; for (const [key, value] of Object.entries(values)) params.set(key, value); window.history.replaceState(null, "", `${window.location.pathname}?${params}`); }, [selection]);

  const updateSelection = useCallback((patch: Partial<Omit<Selection, "runId">>) => setSelection((current) => current ? { ...current, ...patch } : null), []);
  const applyRange = useCallback(() => { if (!metadata) return; if (!/^\d{4}-\d{2}-\d{2}$/.test(draftFrom) || !/^\d{4}-\d{2}-\d{2}$/.test(draftTo)) { setError("Заполните обе даты периода."); return; } if (draftFrom > draftTo) { setError("Начало периода не может быть позже окончания."); return; } const range = clampRange(draftFrom, draftTo, metadata.forecast_start, metadata.forecast_end); setDraftFrom(range.from); setDraftTo(range.to); updateSelection({ ...range, date: range.from }); }, [draftFrom, draftTo, metadata, updateSelection]);
  const setQuickRange = useCallback((kind: "NOV" | "DEC" | "ALL") => { if (!metadata) return; const raw = kind === "NOV" ? { from: "2025-11-01", to: "2025-11-30" } : kind === "DEC" ? { from: "2025-12-01", to: "2025-12-31" } : { from: metadata.forecast_start, to: metadata.forecast_end }; const range = clampRange(raw.from, raw.to, metadata.forecast_start, metadata.forecast_end); setDraftFrom(range.from); setDraftTo(range.to); setSelection((current) => current ? { ...current, ...range, date: range.from } : null); }, [metadata]);
  const exportCsv = useCallback(async (onlyHour: boolean) => { if (!selection || !metadata) return; setExporting(true); setExportMessage(null); try { const month = monthBounds(selection.month); const range = selection.view === "DAY" ? { from: selection.date, to: selection.date } : selection.view === "MONTH" ? clampRange(month.from, month.to, metadata.forecast_start, metadata.forecast_end) : { from: selection.from, to: selection.to }; const result = await client.exportCsv({ runId: selection.runId, route: selection.route, ...range, hour: onlyHour ? selection.hour : undefined }); const url = URL.createObjectURL(result.blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = result.filename; anchor.click(); URL.revokeObjectURL(url); setExportMessage(`Файл ${result.filename} подготовлен.`); } catch (cause) { setExportMessage(presentError(cause)); } finally { setExporting(false); } }, [client, metadata, selection]);

  const selectedPoint = pointRows.length === 1 ? pointRows[0] : null; const totalPrediction = pointRows.reduce((sum, item) => sum + item.prediction, 0); const periodTotal = [...forecastPoints, ...aggregatePoints].reduce((sum, item) => sum + item.prediction, 0);
  const supportedRoutes = useMemo(() => routes.length ? routes : COMPETITION_ROUTES.map((route) => ({ route, name: `Трамвай ${route}`, gtfs_route_ids: [], geometry_available: false, forecast_available: false })), [routes]);
  return { phase, selection, metadata, routes, supportedRoutes, forecastPoints, aggregatePoints, pointRows, selectedPoint, totalPrediction, periodTotal, dataLoading, error, notice, draftFrom, draftTo, setDraftFrom, setDraftTo, updateSelection, applyRange, setQuickRange, exporting, exportMessage, exportCsv, retry: () => setAttempt((value) => value + 1), route: routes.find((item) => item.route === selection?.route) ?? null };
}
