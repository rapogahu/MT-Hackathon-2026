import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { presentError } from "../api/errors";
import type { DirectionsResponse, ForecastDataClient, MapRoutesResponse, RouteSegment, RouteStop } from "../api/types";
import type { Selection } from "./useForecastDashboard";

type MapPhase = "idle" | "loading" | "ready" | "empty" | "error";

export function useForecastGeography(client: ForecastDataClient, selection: Selection | null) {
  const [phase, setPhase] = useState<MapPhase>("idle"); const [mapData, setMapData] = useState<MapRoutesResponse | null>(null);
  const [directions, setDirections] = useState<DirectionsResponse | null>(null); const [stops, setStops] = useState<RouteStop[]>([]); const [segments, setSegments] = useState<RouteSegment[]>([]);
  const [geometryId, setGeometryId] = useState<string | null>(null); const [stopKey, setStopKey] = useState<string | null>(null); const [segmentId, setSegmentId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null); const [attempt, setAttempt] = useState(0);
  const mapSequence = useRef(0); const navigationSequence = useRef(0); const knownReference = useRef<string | null>(null);

  useEffect(() => {
    if (!selection) { setPhase("idle"); return; }
    const controller = new AbortController(); const requestId = ++mapSequence.current;
    setPhase((current) => mapData ? current : "loading"); setError(null);
    void client.getMapRoutes({ runId: selection.runId, route: selection.route, date: selection.date, hour: selection.hour }, { signal: controller.signal }).then((map) => {
      if (requestId !== mapSequence.current) return;
      if (knownReference.current && knownReference.current !== map.reference_version) { setGeometryId(null); setStopKey(null); setSegmentId(null); setStops([]); setSegments([]); }
      knownReference.current = map.reference_version; setMapData(map); setPhase(map.features.length ? "ready" : "empty");
    }).catch((cause) => { if (requestId !== mapSequence.current || (cause instanceof Error && cause.name === "AbortError")) return; setPhase("error"); setError(presentError(cause)); });
    return () => controller.abort();
  }, [attempt, client, selection?.runId, selection?.route, selection?.date, selection?.hour]);

  useEffect(() => {
    setMapData(null); setPhase(selection ? "loading" : "idle"); setDirections(null); setStops([]); setSegments([]); setGeometryId(null); setStopKey(null); setSegmentId(null);
    if (!selection || selection.route === null) return;
    const controller = new AbortController();
    void client.getDirections(selection.route, { signal: controller.signal }).then((response) => {
      if (knownReference.current && knownReference.current !== response.reference_version) { setMapData(null); }
      knownReference.current = response.reference_version; setDirections(response);
      const requested = new URLSearchParams(window.location.search).get("geometry");
      setGeometryId(response.directions.some((item) => item.geometry_id === requested) ? requested : response.directions[0]?.geometry_id ?? null);
    }).catch((cause) => { if (cause instanceof Error && cause.name === "AbortError") return; setError(presentError(cause)); });
    return () => controller.abort();
  }, [attempt, client, selection?.route]);

  const selectedDirection = useMemo(() => directions?.directions.find((item) => item.geometry_id === geometryId) ?? null, [directions, geometryId]);
  useEffect(() => {
    if (!selection || selection.route === null || !selectedDirection || !directions) return;
    const controller = new AbortController(); const requestId = ++navigationSequence.current; setStops([]); setSegments([]); setStopKey(null); setSegmentId(null);
    const input = { route: selection.route, tripId: selectedDirection.trip_id, directionId: selectedDirection.direction_id };
    void Promise.all([client.getStops(input, { signal: controller.signal }), client.getSegments(input, { signal: controller.signal })]).then(([stopResponse, segmentResponse]) => {
      if (requestId !== navigationSequence.current) return;
      if (stopResponse.reference_version !== directions.reference_version || segmentResponse.reference_version !== directions.reference_version) throw new Error("Версия справочника изменилась. Выберите географию заново.");
      const nextStops = stopResponse.stops.filter((item) => item.geometry_id === selectedDirection.geometry_id); const nextSegments = segmentResponse.segments.filter((item) => item.geometry_id === selectedDirection.geometry_id);
      setStops(nextStops); setSegments(nextSegments);
      const params = new URLSearchParams(window.location.search); const requestedStop = params.get("stop"); const requestedSegment = params.get("segment");
      if (nextStops.some((item) => `${item.geometry_id}:${item.stop_sequence}` === requestedStop)) setStopKey(requestedStop);
      if (nextSegments.some((item) => item.segment_id === requestedSegment)) setSegmentId(requestedSegment);
    }).catch((cause) => { if (requestId !== navigationSequence.current || (cause instanceof Error && cause.name === "AbortError")) return; setError(presentError(cause)); });
    return () => controller.abort();
  }, [client, directions, selectedDirection, selection?.route]);

  useEffect(() => {
    if (!selection) return; const params = new URLSearchParams(window.location.search); const referenceVersion = mapData?.reference_version ?? directions?.reference_version;
    const values: Array<[string, string | null | undefined]> = [["reference", referenceVersion], ["geometry", selection.route === null ? null : geometryId], ["stop", selection.route === null ? null : stopKey], ["segment", selection.route === null ? null : segmentId]];
    for (const [key, value] of values) value ? params.set(key, value) : params.delete(key); window.history.replaceState(null, "", `${window.location.pathname}?${params}`);
  }, [directions?.reference_version, geometryId, mapData?.reference_version, segmentId, selection, stopKey]);

  const selectGeometry = useCallback((value: string | null) => { setGeometryId(value); setStopKey(null); setSegmentId(null); }, []);
  const selectStop = useCallback((value: string | null) => { setStopKey(value); setSegmentId(null); }, []); const selectSegment = useCallback((value: string | null) => { setSegmentId(value); setStopKey(null); }, []);
  return { phase, mapData, directions: directions?.directions ?? [], stops, segments, geometryId, selectedDirection, stopKey, selectedStop: stops.find((item) => `${item.geometry_id}:${item.stop_sequence}` === stopKey) ?? null, segmentId, selectedSegment: segments.find((item) => item.segment_id === segmentId) ?? null, error, selectGeometry, selectStop, selectSegment, retry: () => setAttempt((value) => value + 1) };
}
