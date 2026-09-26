import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import type { ForecastPoint } from "../api/types";

interface ForecastChartProps {
  points: ForecastPoint[];
  selectedHour: number;
  onHourSelect: (hour: number) => void;
}

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

const categoryLabels: Record<ForecastPoint["load_category"], string> = {
  very_low: "Очень низкая",
  low: "Низкая",
  medium: "Средняя",
  high: "Высокая",
  very_high: "Очень высокая",
};

export function ForecastChart({ points, selectedHour, onHourSelect }: ForecastChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const onSelectRef = useRef(onHourSelect);
  onSelectRef.current = onHourSelect;

  useEffect(() => {
    if (!chartRef.current || navigator.userAgent.includes("jsdom")) return;
    const chart = echarts.init(chartRef.current, undefined, { renderer: "canvas" });
    chart.setOption({
      animationDuration: 350,
      grid: { top: 24, right: 18, bottom: 44, left: 56 },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#10242e",
        borderColor: "#27434f",
        textStyle: { color: "#f5fbf8" },
        formatter: (items: unknown) => {
          const item = Array.isArray(items) ? items[0] : items;
          const index = (item as { dataIndex?: number } | undefined)?.dataIndex ?? 0;
          const point = points[index];
          if (!point) return "";
          return [
            `<strong>${String(point.hour).padStart(2, "0")}:00–${String(point.hour).padStart(2, "0")}:59</strong>`,
            `Прогноз посадок: ${Math.floor(point.prediction + 0.5).toLocaleString("ru-RU")}`,
            `Относительная загрузка: ${point.relative_load_pct}%`,
            `Индекс: ${point.load_index}/10 — ${categoryLabels[point.load_category]}`,
          ].join("<br/>");
        },
      },
      xAxis: {
        type: "category",
        data: points.map((point) => `${String(point.hour).padStart(2, "0")}:00`),
        axisLine: { lineStyle: { color: "#49626d" } },
        axisLabel: { color: "#9eb0b7", interval: 2 },
      },
      yAxis: {
        type: "value",
        name: "посадки",
        nameTextStyle: { color: "#9eb0b7" },
        splitLine: { lineStyle: { color: "rgba(158, 176, 183, .13)" } },
        axisLabel: { color: "#9eb0b7" },
      },
      series: [
        {
          type: "line",
          smooth: 0.28,
          symbolSize: (value: unknown, params: { dataIndex: number }) =>
            points[params.dataIndex]?.hour === selectedHour ? 11 : 5,
          data: points.map((point) => point.prediction),
          lineStyle: { color: "#b9f45d", width: 3 },
          itemStyle: { color: "#d9ff98", borderColor: "#0b1820", borderWidth: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(185, 244, 93, .30)" },
              { offset: 1, color: "rgba(185, 244, 93, 0)" },
            ]),
          },
        },
      ],
    });
    chart.on("click", (params: { dataIndex?: number }) => {
      const point = params.dataIndex === undefined ? undefined : points[params.dataIndex];
      if (point) onSelectRef.current(point.hour);
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(chartRef.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [points, selectedHour]);

  return (
    <div className="chart-wrap">
      <div
        ref={chartRef}
        className="chart-canvas"
        role="img"
        aria-label={`Почасовой график из ${points.length} точек. Выбран ${selectedHour}:00.`}
        data-testid="forecast-chart"
      />
      <div className="hour-rail" aria-label="Выбор часа по графику">
        {points.map((point) => (
          <button
            type="button"
            key={point.hour}
            className={point.hour === selectedHour ? "hour-dot is-active" : "hour-dot"}
            aria-label={`${String(point.hour).padStart(2, "0")}:00, ${Math.floor(point.prediction + 0.5)} посадок`}
            aria-pressed={point.hour === selectedHour}
            onClick={() => onHourSelect(point.hour)}
          >
            <span>{String(point.hour).padStart(2, "0")}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
