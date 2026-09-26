import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, MapEventType, MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";
import type { MapRoutesResponse, RouteStop } from "../api/types";

interface Props {
  data: MapRoutesResponse;
  fitKey: string;
  geometryId: string | null;
  stops: RouteStop[];
  loadIndexes: Record<number, number>;
  onRouteSelect: (route: number) => void;
}

interface ProjectedRoute { key: string; route: number; color: string; points: string }
interface ProjectedStop { key: string; x: number; y: number; color: string; stop: RouteStop }

const fallbackStyle: StyleSpecification = {
  version: 8,
  sources: {
    openstreetmap: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
      maxzoom: 19,
    },
  },
  layers: [
    { id: "background", type: "background", paint: { "background-color": "#e7eefc" } },
    { id: "openstreetmap", type: "raster", source: "openstreetmap", paint: { "raster-saturation": -.55, "raster-contrast": .16, "raster-brightness-max": .82, "raster-opacity": .82 } },
  ],
};

const loadColor = [
  "step", ["to-number", ["get", "load_index"], 1],
  "#38BDF8", 3, "#2563EB", 5, "#D39A00", 7, "#F06418", 9, "#DC2626",
] as const;

export function ForecastMap({ data, fitKey, geometryId, stops, loadIndexes, onRouteSelect }: Props) {
  const shellRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const selectRouteRef = useRef(onRouteSelect); selectRouteRef.current = onRouteSelect;
  const lastFitKey = useRef<string | null>(null);
  const [generation, setGeneration] = useState(0);
  const [styleError, setStyleError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [projectedRoutes, setProjectedRoutes] = useState<ProjectedRoute[]>([]);
  const [projectedStops, setProjectedStops] = useState<ProjectedStop[]>([]);
  const [hoveredStopKey, setHoveredStopKey] = useState<string | null>(null);
  const renderedData = useMemo(() => withLoadIndexes(data, loadIndexes), [data, loadIndexes]);
  const renderedDataRef = useRef(renderedData); renderedDataRef.current = renderedData;
  const stopsRef = useRef(stops); stopsRef.current = stops;
  const loadIndexesRef = useRef(loadIndexes); loadIndexesRef.current = loadIndexes;
  const primary = renderedData.features.find((feature) => geometryId === null || feature.properties.geometry_id === geometryId) ?? renderedData.features[0];
  const primaryIndex = primary ? clampIndex(primary.properties.load_index) : null;

  useEffect(() => {
    if (!containerRef.current || navigator.userAgent.includes("jsdom")) return;
    let disposed = false;
    setReady(false); setStyleError(null);
    const styleUrl = import.meta.env.VITE_MAP_STYLE_URL?.trim();
    const map = new maplibregl.Map({ container: containerRef.current, style: styleUrl || fallbackStyle, center: [37.62, 55.75], zoom: 10, attributionControl: {} });
    mapRef.current = map;
    const redrawOverlay = () => { if (!disposed) { setProjectedRoutes(projectRoutes(map, renderedDataRef.current)); setProjectedStops(projectStops(map, stopsRef.current, loadIndexesRef.current)); } };
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    focusRoute(map, renderedData);
    redrawOverlay();
    const handleError = (event: MapEventType["error"]) => { if (styleUrl && !map.loaded()) setStyleError(event.error?.message ?? "Не удалось загрузить стиль карты"); };
    map.on("error", handleError);
    map.on("load", () => {
      if (disposed) return;
      map.addSource("forecast-routes", { type: "geojson", data: renderedData as never });
      map.addLayer({ id: "route-shadow", type: "line", source: "forecast-routes", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#061014", "line-width": 26, "line-opacity": .96, "line-blur": 1.5 } });
      map.addLayer({ id: "route-contrast", type: "line", source: "forecast-routes", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#ffffff", "line-width": 19, "line-opacity": 1 } });
      map.addLayer({ id: "forecast-route", type: "line", source: "forecast-routes", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": lineColor(renderedData) as never, "line-width": 13, "line-opacity": 1 } });
      map.on("click", "forecast-route", (event: MapLayerMouseEvent) => {
        const properties = event.features?.[0]?.properties as Record<string, string | number | boolean> | undefined;
        if (properties) selectRouteRef.current(Number(properties.route));
      });
      map.on("mouseenter", "forecast-route", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "forecast-route", () => { map.getCanvas().style.cursor = ""; });
      map.resize();
      focusRoute(map, renderedData);
      redrawOverlay();
      lastFitKey.current = fitKey;
      setReady(true);
    });
    map.on("move", redrawOverlay);
    map.on("zoom", redrawOverlay);
    map.on("resize", redrawOverlay);
    return () => { disposed = true; map.off("error", handleError); map.off("move", redrawOverlay); map.off("zoom", redrawOverlay); map.off("resize", redrawOverlay); map.remove(); if (mapRef.current === map) mapRef.current = null; lastFitKey.current = null; };
  }, [generation]);

  useEffect(() => {
    const map = mapRef.current; if (!map || !ready) return;
    const source = map.getSource("forecast-routes") as GeoJSONSource | undefined;
    if (!source) return;
    source.setData(renderedData as never);
    map.setPaintProperty("forecast-route", "line-color", lineColor(renderedData) as never);
    if (fitKey !== lastFitKey.current) { map.resize(); focusRoute(map, renderedData); lastFitKey.current = fitKey; }
    setProjectedRoutes(projectRoutes(map, renderedData));
    setProjectedStops(projectStops(map, stops, loadIndexes));
  }, [fitKey, geometryId, loadIndexes, ready, renderedData, stops]);

  useEffect(() => {
    const shell = shellRef.current; if (!shell || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => { const map = mapRef.current; if (!map) return; map.resize(); setProjectedRoutes(projectRoutes(map, renderedDataRef.current)); setProjectedStops(projectStops(map, stopsRef.current, loadIndexesRef.current)); });
    observer.observe(shell);
    return () => observer.disconnect();
  }, []);

  const hoveredStop = projectedStops.find((item) => item.key === hoveredStopKey) ?? null;
  return <div ref={shellRef} className="forecast-map-shell resizable-map-shell" data-fit-key={fitKey}>
    <div ref={containerRef} className="forecast-map" data-testid="forecast-map" role="img" aria-label={`Карта маршрута: ${data.features.length} вариантов пути.`} />
    <svg className="map-route-overlay" aria-hidden="true">
      {projectedRoutes.map((route) => <g key={route.key}>
        <polyline points={route.points} fill="none" stroke="#061014" strokeWidth="26" strokeLinecap="round" strokeLinejoin="round" opacity=".95" />
        <polyline points={route.points} fill="none" stroke="#fff" strokeWidth="19" strokeLinecap="round" strokeLinejoin="round" opacity="1" />
        <polyline data-testid={`visible-map-route-${route.route}`} points={route.points} fill="none" stroke={route.color} strokeWidth="13" strokeLinecap="round" strokeLinejoin="round" opacity="1" />
      </g>)}
      {projectedStops.map((item) => <circle key={item.key} className="map-stop-point" data-testid={`map-stop-${item.stop.stop_id}`} cx={item.x} cy={item.y} r={hoveredStopKey === item.key ? 9 : 6} fill="#fff" stroke={item.color} strokeWidth="4" role="button" tabIndex={0} aria-label={`Остановка ${item.stop.stop_name}`} onMouseEnter={() => setHoveredStopKey(item.key)} onMouseLeave={() => setHoveredStopKey(null)} onFocus={() => setHoveredStopKey(item.key)} onBlur={() => setHoveredStopKey(null)}><title>{item.stop.stop_name}</title></circle>)}
    </svg>
    {hoveredStop && <div className="map-stop-tooltip" style={{ left: hoveredStop.x, top: hoveredStop.y }} role="tooltip"><strong>{hoveredStop.stop.stop_name}</strong><span>Остановка №{hoveredStop.stop.stop_sequence} по маршруту</span></div>}
    <div className="map-load-summary" aria-live="polite"><span>Маршрут {primary?.properties.route ?? "—"} · {primary?.geometry.coordinates.length ?? 0} точек</span><strong style={{ color: primaryIndex === null ? undefined : colorForIndex(primaryIndex) }}>Индекс загрузки {primaryIndex ?? "—"}/10</strong><small>{primaryIndex === null ? "Нет данных о загрузке" : categoryForIndex(primaryIndex)}</small></div>
    <div className="map-resize-hint" aria-hidden="true">↕ Потяните нижний край, чтобы изменить высоту</div>
    {styleError && <div className="map-overlay" role="alert"><strong>Подложка карты недоступна</strong><span>{styleError}</span><button type="button" onClick={() => setGeneration((value) => value + 1)}>Повторить</button></div>}
    <div className="map-legend" aria-label="Категории загрузки"><Legend color="#38BDF8" label="1–2 Очень низкая" /><Legend color="#2563EB" label="3–4 Низкая" /><Legend color="#D39A00" label="5–6 Средняя" /><Legend color="#F06418" label="7–8 Высокая" /><Legend color="#DC2626" label="9–10 Очень высокая" /></div>
  </div>;
}

function Legend({ color, label }: { color: string; label: string }) { return <span><i style={{ background: color }} />{label}</span>; }
function withLoadIndexes(data: MapRoutesResponse, loadIndexes: Record<number, number>): MapRoutesResponse { return { ...data, features: data.features.map((feature) => ({ ...feature, properties: { ...feature.properties, load_index: loadIndexes[feature.properties.route] ?? feature.properties.load_index } })) }; }
function lineColor(data: MapRoutesResponse) { const routes = new Set(data.features.map((feature) => feature.properties.route)); if (routes.size === 1 && data.features[0]) return colorForIndex(clampIndex(data.features[0].properties.load_index)); return loadColor; }
function clampIndex(value: number) { return Math.max(1, Math.min(10, Math.round(Number.isFinite(value) ? value : 1))); }
function colorForIndex(index: number) { if (index <= 2) return "#38BDF8"; if (index <= 4) return "#2563EB"; if (index <= 6) return "#D39A00"; if (index <= 8) return "#F06418"; return "#DC2626"; }
function categoryForIndex(index: number) { if (index <= 2) return "Очень низкая загрузка"; if (index <= 4) return "Низкая загрузка"; if (index <= 6) return "Средняя загрузка"; if (index <= 8) return "Высокая загрузка"; return "Очень высокая загрузка"; }
function boundsFor(data: MapRoutesResponse): maplibregl.LngLatBounds | null { const coordinates = data.features.flatMap((feature) => feature.geometry.coordinates); if (!coordinates.length) return null; const bounds = new maplibregl.LngLatBounds(coordinates[0], coordinates[0]); for (const coordinate of coordinates.slice(1)) bounds.extend(coordinate); return bounds; }
function focusRoute(map: MapLibreMap, data: MapRoutesResponse) { const bounds = boundsFor(data); if (bounds) map.fitBounds(bounds, { padding: 90, maxZoom: 13, duration: 0 }); }
function projectRoutes(map: MapLibreMap, data: MapRoutesResponse): ProjectedRoute[] { return data.features.map((feature, index) => ({ key: String(feature.properties.geometry_id || feature.id || `${feature.properties.route}-${index}`), route: feature.properties.route, color: colorForIndex(clampIndex(feature.properties.load_index)), points: feature.geometry.coordinates.map((coordinate) => { const point = map.project(coordinate); return `${point.x},${point.y}`; }).join(" ") })); }
function projectStops(map: MapLibreMap, stops: RouteStop[], loadIndexes: Record<number, number>): ProjectedStop[] { return stops.map((stop) => { const point = map.project([stop.lon, stop.lat]); return { key: `${stop.geometry_id}:${stop.stop_sequence}`, x: point.x, y: point.y, color: colorForIndex(clampIndex(loadIndexes[stop.route] ?? 1)), stop }; }); }
