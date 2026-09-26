import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { presentError } from "../api/errors";
import type { DirectionsResponse, ForecastDataClient, MapRoutesResponse, RouteStop } from "../api/types";
import type { Selection } from "./useForecastDashboard";

type MapPhase = "idle" | "loading" | "ready" | "empty" | "error";

export function useForecastGeography(client: ForecastDataClient, selection: Selection | null) {
  const [phase, setPhase] = useState<MapPhase>("idle"); const [mapData, setMapData] = useState<MapRoutesResponse | null>(null);
  const [directions, setDirections] = useState<DirectionsResponse | null>(null); const [stops, setStops] = useState<RouteStop[]>([]);
  const [geometryId, setGeometryId] = useState<string | null>(null); const [stopKey, setStopKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null); const [attempt, setAttempt] = useState(0);
  const mapSequence = useRef(0); const navigationSequence = useRef(0); const knownReference = useRef<string | null>(null);

  useEffect(() => {
    if (!selection) { setPhase("idle"); return; }
    const controller = new AbortController(); const requestId = ++mapSequence.current;
    setPhase((current) => mapData ? current : "loading"); setError(null);
    void client.getMapRoutes({ runId: selection.runId, route: selection.route, date: selection.date, hour: selection.hour }, { signal: controller.signal }).then((map) => {
      if (requestId !== mapSequence.current) return;
      if (knownReference.current && knownReference.current !== map.reference_version) { setGeometryId(null); setStopKey(null); setStops([]); }
      knownReference.current = map.reference_version; setMapData(map); setPhase(map.features.length ? "ready" : "empty");
    }).catch((cause) => { if (requestId !== mapSequence.current || (cause instanceof Error && cause.name === "AbortError")) return; setPhase("error"); setError(presentError(cause)); });
    return () => controller.abort();
  }, [attempt, client, selection?.runId, selection?.route, selection?.date, selection?.hour]);

  useEffect(() => {
    setMapData(null); setPhase(selection ? "loading" : "idle"); setDirections(null); setStops([]); setGeometryId(null); setStopKey(null);
    if (!selection || selection.route === null) return;
    const controller = new AbortController();
    void client.getDirections(selection.route, { signal: controller.signal }).then((response) => {
      if (knownReference.current && knownReference.current !== response.reference_version) { setMapData(null); }
      knownReference.current = response.reference_version; setDirections(response);
      setGeometryId(response.directions[0]?.geometry_id ?? null);
    }).catch((cause) => { if (cause instanceof Error && cause.name === "AbortError") return; setError(presentError(cause)); });
    return () => controller.abort();
  }, [attempt, client, selection?.route]);

  const selectedDirection = useMemo(() => directions?.directions.find((item) => item.geometry_id === geometryId) ?? null, [directions, geometryId]);
  useEffect(() => {
    if (!selection || selection.route === null || !selectedDirection || !directions) return;
    const controller = new AbortController(); const requestId = ++navigationSequence.current; setStops([]); setStopKey(null);
    const input = { route: selection.route, tripId: selectedDirection.trip_id, directionId: selectedDirection.direction_id };
    void client.getStops(input, { signal: controller.signal }).then((stopResponse) => {
      if (requestId !== navigationSequence.current) return;
      if (stopResponse.reference_version !== directions.reference_version) throw new Error("Версия справочника изменилась. Выберите остановку заново.");
      const nextStops = stopResponse.stops.filter((item) => item.geometry_id === selectedDirection.geometry_id); setStops(nextStops);
      const params = new URLSearchParams(window.location.search); const requestedStop = params.get("stop");
      if (nextStops.some((item) => `${item.geometry_id}:${item.stop_sequence}` === requestedStop)) setStopKey(requestedStop);
    }).catch((cause) => { if (requestId !== navigationSequence.current || (cause instanceof Error && cause.name === "AbortError")) return; setError(presentError(cause)); });
    return () => controller.abort();
  }, [client, directions, selectedDirection, selection?.route]);

  useEffect(() => {
    if (!selection) return; const params = new URLSearchParams(window.location.search); const referenceVersion = mapData?.reference_version ?? directions?.reference_version;
    const values: Array<[string, string | null | undefined]> = [["reference", referenceVersion], ["geometry", null], ["stop", selection.route === null ? null : stopKey], ["segment", null]];
    for (const [key, value] of values) value ? params.set(key, value) : params.delete(key); window.history.replaceState(null, "", `${window.location.pathname}?${params}`);
  }, [directions?.reference_version, mapData?.reference_version, selection, stopKey]);

  const selectStop = useCallback((value: string | null) => { setStopKey(value); }, []);
  return { phase, mapData, stops, geometryId, stopKey, selectedStop: stops.find((item) => `${item.geometry_id}:${item.stop_sequence}` === stopKey) ?? null, error, selectStop, retry: () => setAttempt((value) => value + 1) };
}
