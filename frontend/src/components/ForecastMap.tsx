import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, MapEventType, MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import type { MapRoutesResponse, RouteSegment, RouteStop } from "../api/types";

interface Props { data: MapRoutesResponse; fitKey: string; geometryId: string | null; stops: RouteStop[]; selectedStop: RouteStop | null; selectedSegment: RouteSegment | null; onRouteSelect: (route: number) => void }
const localStyle: StyleSpecification = { version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": "#09171d" } }] };
const categoryColor = ["match", ["get", "load_category"], "very_low", "#2563EB", "low", "#16A34A", "medium", "#CA8A04", "high", "#EA580C", "very_high", "#DC2626", "#9eb0b7"] as const;

export function ForecastMap({ data, fitKey, geometryId, stops, selectedStop, selectedSegment, onRouteSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null); const mapRef = useRef<MapLibreMap | null>(null); const selectRouteRef = useRef(onRouteSelect); selectRouteRef.current = onRouteSelect;
  const lastFitKey = useRef<string | null>(null); const [generation, setGeneration] = useState(0); const [styleError, setStyleError] = useState<string | null>(null); const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!containerRef.current || navigator.userAgent.includes("jsdom")) return;
    setReady(false); setStyleError(null);
    const style = import.meta.env.VITE_MAP_STYLE_URL?.trim() || localStyle;
    const map = new maplibregl.Map({ container: containerRef.current, style, center: [37.62, 55.75], zoom: 10, attributionControl: {} });
    mapRef.current = map; map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    const handleError = (event: MapEventType["error"]) => { if (!map.loaded()) setStyleError(event.error?.message ?? "Не удалось загрузить стиль карты"); };
    map.on("error", handleError);
    map.on("load", () => {
      map.addSource("forecast-routes", { type: "geojson", data: data as never });
      map.addSource("route-stops", { type: "geojson", data: emptyCollection() });
      map.addSource("selected-segment", { type: "geojson", data: emptyCollection() });
      map.addLayer({ id: "route-outline", type: "line", source: "forecast-routes", paint: { "line-color": "#071116", "line-width": ["case", ["==", ["get", "geometry_id"], geometryId ?? ""], 10, 7], "line-opacity": .88 } });
      map.addLayer({ id: "forecast-route", type: "line", source: "forecast-routes", paint: { "line-color": categoryColor as never, "line-width": ["case", ["==", ["get", "geometry_id"], geometryId ?? ""], 6, 4], "line-opacity": .96 } });
      map.addLayer({ id: "selected-segment", type: "line", source: "selected-segment", paint: { "line-color": "#ffffff", "line-width": 9, "line-opacity": .92 } });
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
    (map.getSource("forecast-routes") as GeoJSONSource | undefined)?.setData(data as never);
    (map.getSource("route-stops") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: stops.map((stop) => ({ type: "Feature", geometry: { type: "Point", coordinates: [stop.lon, stop.lat] }, properties: stop })) } as never);
    (map.getSource("selected-segment") as GeoJSONSource | undefined)?.setData(selectedSegment ? { type: "FeatureCollection", features: [{ type: "Feature", geometry: selectedSegment.geometry, properties: selectedSegment }] } as never : emptyCollection());
    map.setPaintProperty("route-outline", "line-width", ["case", ["==", ["get", "geometry_id"], geometryId ?? ""], 10, 7]);
    map.setPaintProperty("forecast-route", "line-width", ["case", ["==", ["get", "geometry_id"], geometryId ?? ""], 6, 4]);
    if (fitKey !== lastFitKey.current) { const bounds = boundsFor(data); if (bounds) map.fitBounds(bounds, { padding: 48, maxZoom: 14, duration: 0 }); lastFitKey.current = fitKey; }
  }, [data, fitKey, geometryId, ready, selectedSegment, stops]);

  useEffect(() => { const map = mapRef.current; if (!map || !ready || !selectedStop) return; map.easeTo({ center: [selectedStop.lon, selectedStop.lat], zoom: Math.max(map.getZoom(), 14), duration: 350 }); new maplibregl.Popup().setLngLat([selectedStop.lon, selectedStop.lat]).setHTML(`<strong>${escapeHtml(selectedStop.stop_name)}</strong><br/>stop_id: ${escapeHtml(selectedStop.stop_id)}<br/>Направление ${selectedStop.direction_id}, позиция ${selectedStop.stop_sequence}<br/><em>Прогноз — по маршруту целиком</em>`).addTo(map); }, [ready, selectedStop]);

  return <div className="forecast-map-shell"><div ref={containerRef} className="forecast-map" data-testid="forecast-map" role="img" aria-label={`Справочная карта: ${data.features.length} вариантов пути.`} />{styleError && <div className="map-overlay" role="alert"><strong>Подложка карты недоступна</strong><span>{styleError}</span><button type="button" onClick={() => setGeneration((value) => value + 1)}>Повторить</button></div>}<div className="map-legend" aria-label="Категории загрузки"><span><i style={{ background: "#2563EB" }} />Очень низкая</span><span><i style={{ background: "#16A34A" }} />Низкая</span><span><i style={{ background: "#CA8A04" }} />Средняя</span><span><i style={{ background: "#EA580C" }} />Высокая</span><span><i style={{ background: "#DC2626" }} />Очень высокая</span></div></div>;
}

function emptyCollection() { return { type: "FeatureCollection" as const, features: [] }; }
function boundsFor(data: MapRoutesResponse): maplibregl.LngLatBounds | null { const coordinates = data.features.flatMap((feature) => feature.geometry.coordinates); if (!coordinates.length) return null; const bounds = new maplibregl.LngLatBounds(coordinates[0], coordinates[0]); for (const coordinate of coordinates.slice(1)) bounds.extend(coordinate); return bounds; }
function escapeHtml(value: unknown) { return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character] ?? character); }
function routePopup(properties: Record<string, string | number | boolean>) { const outside = properties.outside_validity_period === true || properties.outside_validity_period === "true"; return `<strong>Маршрут ${escapeHtml(properties.route)}</strong><br/>${escapeHtml(properties.date)}, ${String(properties.hour).padStart(2, "0")}:00<br/>Посадки: ${escapeHtml(properties.prediction)}<br/>Загрузка: ${escapeHtml(properties.relative_load_pct)}%, индекс ${escapeHtml(properties.load_index)}/10<br/>Направление ${escapeHtml(properties.direction_id)}<br/>Схема действует с ${escapeHtml(properties.valid_from)}<br/>Актуализация: ${escapeHtml(properties.reference_actual_date)}${outside ? "<br/><strong>Выбранная дата вне периода действия этой схемы</strong>" : ""}`; }
