import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MapRoutesResponse } from "../api/types";

const remove = vi.fn(); const addSource = vi.fn(); const addLayer = vi.fn(); const constructMap = vi.fn();
vi.mock("maplibre-gl", () => {
  class FakeMap {
    constructor(options: unknown) { constructMap(options); }
    addControl() {} on(event: string, _layerOrHandler: unknown, handler?: () => void) { if (event === "load") queueMicrotask((_layerOrHandler as () => void)); if (event === "click" && handler) return; }
    off() {} remove = remove; addSource = addSource; addLayer = addLayer; getSource() { return { setData: vi.fn() }; } setPaintProperty() {} fitBounds() {} getCanvas() { return { style: { cursor: "" } }; } easeTo() {} getZoom() { return 10; } loaded() { return true; }
  }
  class Bounds { extend() { return this; } }
  class Popup { setLngLat() { return this; } setHTML() { return this; } addTo() { return this; } }
  return { Map: FakeMap, NavigationControl: class {}, LngLatBounds: Bounds, Popup };
});

import { ForecastMap } from "./ForecastMap";

const data: MapRoutesResponse = { type: "FeatureCollection", run_id: "run", date: "2025-11-01", hour: 8, reference_version: "ref", geometry_mode: "reference", features: [{ type: "Feature", id: "g", geometry: { type: "LineString", coordinates: [[37.5, 55.7], [37.6, 55.8]] }, properties: { route: 1, route_id: "4450", trip_id: "t", direction_id: 0, geometry_id: "g", valid_from: "2025-10-11", valid_to: null, reference_actual_date: "2025-12-25", geometry_source: "stop_sequence", outside_validity_period: false, date: "2025-11-01", hour: 8, prediction: 100, relative_load: .5, relative_load_pct: 50, load_index: 5, load_category: "medium", normalization_degenerate: false } }] };

describe("ForecastMap", () => {
  beforeEach(() => { remove.mockClear(); addSource.mockClear(); addLayer.mockClear(); constructMap.mockClear(); Object.defineProperty(navigator, "userAgent", { configurable: true, value: "fixture-browser" }); });
  it("creates contract layers and releases the MapLibre instance", async () => {
    const view = render(<ForecastMap data={data} fitKey="1" geometryId="g" stops={[]} selectedStop={null} loadIndexes={{ 1: 9 }} onRouteSelect={() => undefined} />);
    await waitFor(() => expect(addSource).toHaveBeenCalledWith("forecast-routes", expect.anything()));
    expect(constructMap).toHaveBeenCalledWith(expect.objectContaining({
      style: expect.objectContaining({ sources: expect.objectContaining({ openstreetmap: expect.objectContaining({ type: "raster" }) }) }),
    }));
    expect(addLayer).toHaveBeenCalledWith(expect.objectContaining({
      id: "forecast-route",
      paint: expect.objectContaining({
        "line-color": "#DC2626",
        "line-opacity": 1,
      }),
    }));
    view.unmount();
    expect(remove).toHaveBeenCalledTimes(1);
  });
});
