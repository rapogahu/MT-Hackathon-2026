import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MapRoutesResponse } from "../api/types";

const addSource = vi.fn();
const addLayer = vi.fn();
const setPaintProperty = vi.fn();
const resize = vi.fn();
const fitBounds = vi.fn();

vi.mock("maplibre-gl", () => {
  class FakeMap {
    addControl() {}
    on(event: string, layerOrHandler: unknown, handler?: () => void) { if (event === "load") queueMicrotask(layerOrHandler as () => void); if (handler) return; }
    off() {}
    remove() {}
    addSource = addSource;
    addLayer = addLayer;
    getSource() { return { setData: vi.fn() }; }
    setPaintProperty = setPaintProperty;
    fitBounds = fitBounds;
    getCanvas() { return { style: { cursor: "" } }; }
    loaded() { return true; }
    resize = resize;
    project(coordinate: [number, number]) { return { x: coordinate[0] * 10, y: coordinate[1] * 10 }; }
  }
  class Bounds { extend() { return this; } }
  return { Map: FakeMap, NavigationControl: class {}, LngLatBounds: Bounds };
});

import { ForecastMap } from "./ForecastMap";

const data: MapRoutesResponse = { type: "FeatureCollection", run_id: "run", date: "2025-11-01", hour: 8, reference_version: "ref", geometry_mode: "reference", features: [{ type: "Feature", id: "g", geometry: { type: "LineString", coordinates: [[37.5, 55.7], [37.6, 55.8]] }, properties: { route: 1, route_id: "4450", trip_id: "t", direction_id: 0, geometry_id: "g", valid_from: "2025-10-11", valid_to: null, reference_actual_date: "2025-12-25", geometry_source: "stop_sequence", outside_validity_period: false, date: "2025-11-01", hour: 8, prediction: 100, relative_load: .5, relative_load_pct: 50, load_index: 5, load_category: "medium", normalization_degenerate: false } }] };

describe("ForecastMap", () => {
  beforeEach(() => {
    addSource.mockClear(); addLayer.mockClear(); setPaintProperty.mockClear(); resize.mockClear(); fitBounds.mockClear();
    Object.defineProperty(navigator, "userAgent", { configurable: true, value: "fixture-browser" });
  });

  it("renders a resizable map and paints the route with the supplied load index", async () => {
    render(<ForecastMap data={data} fitKey="1" geometryId="g" stops={[{ route: 1, route_id: "4450", trip_id: "t", direction_id: 0, geometry_id: "g", stop_sequence: 3, stop_id: "stop-3", stop_name: "Тестовая остановка", lat: 55.75, lon: 37.55 }]} loadIndexes={{ 1: 9 }} onRouteSelect={() => undefined} />);
    expect(screen.getByText("Индекс загрузки 9/10")).toBeVisible();
    expect(screen.getByText("Очень высокая загрузка")).toBeVisible();
    expect(screen.getByText(/Потяните нижний край/)).toBeInTheDocument();
    await waitFor(() => expect(addLayer).toHaveBeenCalledWith(expect.objectContaining({ id: "forecast-route", paint: expect.objectContaining({ "line-color": "#DC2626", "line-width": expect.anything() }) })));
    expect(addLayer).toHaveBeenCalledWith(expect.objectContaining({ id: "route-contrast" }));
    expect(fitBounds).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ padding: 90, maxZoom: 13 }));
    expect(screen.getByTestId("visible-map-route-1")).toHaveAttribute("stroke", "#DC2626");
    fireEvent.mouseEnter(screen.getByTestId("map-stop-stop-3"));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Тестовая остановка");
    expect(screen.getByRole("tooltip")).toHaveTextContent("Остановка №3 по маршруту");
    expect(screen.getByRole("tooltip")).not.toHaveTextContent("stop_id");
    expect(screen.getByRole("tooltip")).not.toHaveTextContent("Направление");
  });
});
