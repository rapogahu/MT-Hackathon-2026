import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, MapEventType, MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import type { MapRoutesResponse, RouteStop } from "../api/types";

interface Props { data: MapRoutesResponse; fitKey: string; geometryId: string | null; stops: RouteStop[]; selectedStop: RouteStop | null; loadIndexes: Record<number, number>; onRouteSelect: (route: number) => void }
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
    { id: "background", type: "background", paint: { "background-color": "#dce8e7" } },
    {
      id: "openstreetmap",
      type: "raster",
      source: "openstreetmap",
      paint: { "raster-saturation": -0.45, "raster-contrast": 0.08, "raster-brightness-max": 0.9 },
    },
  ],
};
const loadColor = [
  "step",
  ["to-number", ["get", "load_index"], 0],
  "#E11D48",
  1, "#1473E6",
  3, "#16A34A",
  5, "#D39A00",
  7, "#F06418",
  9, "#DC2626",
] as const;

export function ForecastMap({ data, fitKey, geometryId, stops, selectedStop, loadIndexes, onRouteSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null); const mapRef = useRef<MapLibreMap | null>(null); const selectRouteRef = useRef(onRouteSelect); selectRouteRef.current = onRouteSelect;
  const lastFitKey = useRef<string | null>(null); const [generation, setGeneration] = useState(0); const [styleError, setStyleError] = useState<string | null>(null); const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!containerRef.current || navigator.userAgent.includes("jsdom")) return;
    setReady(false); setStyleError(null);
    const styleUrl = import.meta.env.VITE_MAP_STYLE_URL?.trim();
    const style = styleUrl || fallbackStyle;
    const map = new maplibregl.Map({ container: containerRef.current, style, center: [37.62, 55.75], zoom: 10, attributionControl: {} });
    mapRef.current = map; map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    const handleError = (event: MapEventType["error"]) => { if (styleUrl && !map.loaded()) setStyleError(event.error?.message ?? "Не удалось загрузить стиль карты"); };
    map.on("error", handleError);
    map.on("load", () => {
      const renderedData = withLoadIndexes(data, loadIndexes);
      map.addSource("forecast-routes", { type: "geojson", data: renderedData as never });
      map.addSource("route-stops", { type: "geojson", data: emptyCollection() });
      map.addLayer({ id: "route-outline", type: "line", source: "forecast-routes", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#10242d", "line-width": ["case", ["==", ["get", "geometry_id"], geometryId ?? ""], 15, 12], "line-opacity": .82 } });
      map.addLayer({ id: "forecast-route", type: "line", source: "forecast-routes", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": lineColor(renderedData) as never, "line-width": ["case", ["==", ["get", "geometry_id"], geometryId ?? ""], 11, 8], "line-opacity": 1 } });
      map.addLayer({ id: "route-stops", type: "circle", source: "route-stops", paint: { "circle-radius": 5, "circle-color": "#edf6f2", "circle-stroke-color": "#10242d", "circle-stroke-width": 2 } });
      map.on("click", "forecast-route", (event: MapLayerMouseEvent) => {
        const feature = event.features?.[0]; const properties = feature?.properties as Record<string, string | number | boolean> | undefined; if (!properties) return;
        selectRouteRef.current(Number(properties.route));
        new maplibregl.Popup().setLngLat(event.lngLat).setHTML(routePopup(properties)).addTo(map);
      });
      map.on("mouseenter", "forecast-route", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "forecast-route", () => { map.getCanvas().style.cursor = ""; });
      setReady(true);
    });
    return () => { map.off("error", handleError); map.remove(); mapRef.current = null; lastFitKey.current = null; };
  }, [generation]);

  useEffect(() => {
    const map = mapRef.current; if (!map || !ready) return;
    const renderedData = withLoadIndexes(data, loadIndexes);
    (map.getSource("forecast-routes") as GeoJSONSource | undefined)?.setData(renderedData as never);
    (map.getSource("route-stops") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: stops.map((stop) => ({ type: "Feature", geometry: { type: "Point", coordinates: [stop.lon, stop.lat] }, properties: stop })) } as never);
    map.setPaintProperty("route-outline", "line-width", ["case", ["==", ["get", "geometry_id"], geometryId ?? ""], 15, 12]);
    map.setPaintProperty("forecast-route", "line-color", lineColor(renderedData) as never);
    map.setPaintProperty("forecast-route", "line-width", ["case", ["==", ["get", "geometry_id"], geometryId ?? ""], 11, 8]);
    if (fitKey !== lastFitKey.current) { const bounds = boundsFor(data); if (bounds) map.fitBounds(bounds, { padding: 48, maxZoom: 14, duration: 0 }); lastFitKey.current = fitKey; }
  }, [data, fitKey, geometryId, loadIndexes, ready, stops]);

  useEffect(() => { const map = mapRef.current; if (!map || !ready || !selectedStop) return; map.easeTo({ center: [selectedStop.lon, selectedStop.lat], zoom: Math.max(map.getZoom(), 14), duration: 350 }); new maplibregl.Popup().setLngLat([selectedStop.lon, selectedStop.lat]).setHTML(`<strong>${escapeHtml(selectedStop.stop_name)}</strong><br/>stop_id: ${escapeHtml(selectedStop.stop_id)}<br/>Направление ${escapeHtml(selectedStop.direction_id)}, позиция ${escapeHtml(selectedStop.stop_sequence)}<br/><em>Прогноз — по маршруту целиком</em>`).addTo(map); }, [ready, selectedStop]);

  return <div className="forecast-map-shell"><div ref={containerRef} className="forecast-map" data-testid="forecast-map" role="img" aria-label={`Справочная карта: ${data.features.length} вариантов пути.`} />{styleError && <div className="map-overlay" role="alert"><strong>Подложка карты недоступна</strong><span>{styleError}</span><button type="button" onClick={() => setGeneration((value) => value + 1)}>Повторить</button></div>}<div className="map-legend" aria-label="Категории загрузки"><span><i style={{ background: "#1473E6" }} />Очень низкая</span><span><i style={{ background: "#16A34A" }} />Низкая</span><span><i style={{ background: "#D39A00" }} />Средняя</span><span><i style={{ background: "#F06418" }} />Высокая</span><span><i style={{ background: "#DC2626" }} />Очень высокая</span></div></div>;
}

function emptyCollection() { return { type: "FeatureCollection" as const, features: [] }; }
function withLoadIndexes(data: MapRoutesResponse, loadIndexes: Record<number, number>): MapRoutesResponse { return { ...data, features: data.features.map((feature) => ({ ...feature, properties: { ...feature.properties, load_index: loadIndexes[feature.properties.route] ?? feature.properties.load_index } })) }; }
function lineColor(data: MapRoutesResponse) { const routes = new Set(data.features.map((feature) => feature.properties.route)); if (routes.size === 1 && data.features[0]) return colorForIndex(data.features[0].properties.load_index); return loadColor; }
function colorForIndex(index: number) { if (index <= 2) return "#1473E6"; if (index <= 4) return "#16A34A"; if (index <= 6) return "#D39A00"; if (index <= 8) return "#F06418"; return "#DC2626"; }
function boundsFor(data: MapRoutesResponse): maplibregl.LngLatBounds | null { const coordinates = data.features.flatMap((feature) => feature.geometry.coordinates); if (!coordinates.length) return null; const bounds = new maplibregl.LngLatBounds(coordinates[0], coordinates[0]); for (const coordinate of coordinates.slice(1)) bounds.extend(coordinate); return bounds; }
function escapeHtml(value: unknown) { return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character] ?? character); }
function routePopup(properties: Record<string, string | number | boolean>) { const outside = properties.outside_validity_period === true || properties.outside_validity_period === "true"; return `<strong>Маршрут ${escapeHtml(properties.route)}</strong><br/>${escapeHtml(properties.date)}, ${escapeHtml(String(properties.hour).padStart(2, "0"))}:00<br/>Посадки: ${escapeHtml(properties.prediction)}<br/>Загрузка: ${escapeHtml(properties.relative_load_pct)}%, индекс ${escapeHtml(properties.load_index)}/10<br/>Направление ${escapeHtml(properties.direction_id)}<br/>Схема действует с ${escapeHtml(properties.valid_from)}<br/>Актуализация: ${escapeHtml(properties.reference_actual_date)}${outside ? "<br/><strong>Выбранная дата вне периода действия этой схемы</strong>" : ""}`; }
