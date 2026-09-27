import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";
import type { AggregatePoint, ForecastPoint } from "../api/types";

interface Props { forecastPoints: ForecastPoint[]; aggregatePoints: AggregatePoint[]; selectedHour: number; showHourRail: boolean; onPointSelect: (date: string, hour?: number) => void }
echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);
const colors = ["#2563eb", "#38bdf8", "#f7bf64", "#ef7f96", "#91a7ff", "#c79cff", "#65c7ff", "#60a5fa", "#ff9671", "#1d4ed8"];

export function ForecastChart({ forecastPoints, aggregatePoints, selectedHour, showHourRail, onPointSelect }: Props) {
  const chartRef = useRef<HTMLDivElement>(null); const onSelectRef = useRef(onPointSelect); onSelectRef.current = onPointSelect;
  const points = useMemo(() => forecastPoints.length ? forecastPoints : aggregatePoints, [forecastPoints, aggregatePoints]);
  const routes = useMemo(() => [...new Set(points.map((point) => point.route))], [points]);
  const axis = useMemo(() => [...new Set(points.map((point) => "hour" in point ? `${point.date} ${String(point.hour).padStart(2, "0")}:00` : point.date))].sort(), [points]);
  useEffect(() => {
    if (!chartRef.current || navigator.userAgent.includes("jsdom")) return;
    const chart = echarts.init(chartRef.current, undefined, { renderer: "canvas" });
    chart.setOption({ animationDuration: 250, color: colors, grid: { top: routes.length > 1 ? 54 : 24, right: 18, bottom: 62, left: 68 }, legend: { show: routes.length > 1, textStyle: { color: "#94a3b8" }, data: routes.map((route) => `Маршрут ${route}`) }, tooltip: { trigger: "axis", backgroundColor: "#0f2342", borderColor: "#31517f", textStyle: { color: "#eff6ff" } }, xAxis: { type: "category", data: axis.map((value) => value.slice(5)), axisLabel: { color: "#94a3b8", hideOverlap: true }, axisLine: { lineStyle: { color: "#46658f" } } }, yAxis: { type: "value", name: "посадки", nameTextStyle: { color: "#94a3b8" }, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "rgba(148,163,184,.13)" } } }, series: routes.map((route) => ({ name: `Маршрут ${route}`, type: "line", showSymbol: axis.length <= 62, symbolSize: 6, smooth: axis.length <= 62 ? .2 : 0, data: axis.map((key) => { const found = points.find((point) => point.route === route && ("hour" in point ? `${point.date} ${String(point.hour).padStart(2, "0")}:00` : point.date) === key); return found?.prediction ?? null; }), lineStyle: { width: routes.length > 1 ? 1.5 : 3 } })) });
    chart.on("click", (params: { dataIndex?: number }) => { const key = params.dataIndex === undefined ? undefined : axis[params.dataIndex]; if (!key) return; const [date, time] = key.split(" "); onSelectRef.current(date, time ? Number(time.slice(0, 2)) : undefined); });
    const observer = new ResizeObserver(() => chart.resize()); observer.observe(chartRef.current); return () => { observer.disconnect(); chart.dispose(); };
  }, [axis, points, routes]);
  const dayPoints = forecastPoints.filter((point) => point.route === forecastPoints[0]?.route);
  return <div className="chart-wrap"><div ref={chartRef} className="chart-canvas" role="img" aria-label={`График прогноза: ${points.length} точек, ${routes.length} маршрутов.`} data-testid="forecast-chart" />{showHourRail && <div className="hour-rail" aria-label="Выбор часа по графику">{dayPoints.map((point) => <button type="button" key={point.hour} className={point.hour === selectedHour ? "hour-dot is-active" : "hour-dot"} aria-label={`${String(point.hour).padStart(2, "0")}:00, ${Math.round(point.prediction)} посадок`} aria-pressed={point.hour === selectedHour} onClick={() => onPointSelect(point.date, point.hour)}><span>{String(point.hour).padStart(2, "0")}</span></button>)}</div>}</div>;
}
