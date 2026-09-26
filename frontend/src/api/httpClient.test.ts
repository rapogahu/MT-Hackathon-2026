import { describe, expect, it, vi } from "vitest";
import { HttpForecastClient } from "./httpClient";

describe("HttpForecastClient", () => {
  it("sends the documented DAY and POINT query parameters", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () =>
      new Response(JSON.stringify({ run_id: "run", count: 0, points: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = new HttpForecastClient({ baseUrl: "http://api.test/", fetchImpl: fetchMock });

    await client.getDay({ runId: "run id", route: 17, date: "2025-11-01" });
    await client.getPoint({ runId: "run id", route: 17, date: "2025-11-01", hour: 8 });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://api.test/api/forecast?run_id=run+id&route=17&date=2025-11-01",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://api.test/api/forecast/point?run_id=run+id&route=17&date=2025-11-01&hour=8",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("surfaces an HTTP error and never switches to fixtures", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: { code: "FORECAST_NOT_LOADED", message: "Нет run" } }),
        { status: 503, headers: { "Content-Type": "application/json" } },
      ),
    );
    const client = new HttpForecastClient({ baseUrl: "http://api.test", fetchImpl: fetchMock });

    await expect(client.getRuns()).rejects.toMatchObject({ status: 503, code: "FORECAST_NOT_LOADED" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("preserves a browser AbortError instead of reporting the API as unavailable", async () => {
    const abort = new DOMException("The operation was aborted", "AbortError");
    const fetchMock = vi.fn<typeof fetch>().mockRejectedValue(abort);
    const client = new HttpForecastClient({ baseUrl: "", fetchImpl: fetchMock });

    await expect(client.getRuns()).rejects.toBe(abort);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/forecast/runs",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("omits route for ALL and downloads the backend CSV filename", async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: "run", count: 0, points: [] }), { status: 200 }))
      .mockResolvedValueOnce(new Response("route;date\n1;2025-11-15", { status: 200, headers: { "Content-Type": "text/csv", "Content-Disposition": "attachment; filename=selection.csv" } }));
    const client = new HttpForecastClient({ baseUrl: "http://api.test", fetchImpl: fetchMock });
    await client.getTimeseries({ runId: "run", route: null, from: "2025-11-15", to: "2025-12-05" });
    const exported = await client.exportCsv({ runId: "run", route: null, from: "2025-11-15", to: "2025-12-05" });
    expect(fetchMock.mock.calls[0][0]).toBe("http://api.test/api/forecast/timeseries?run_id=run&from=2025-11-15&to=2025-12-05");
    expect(fetchMock.mock.calls[1][0]).not.toContain("route=");
    expect(exported.filename).toBe("selection.csv");
  });

  it("forms map and reference-navigation URLs without inventing ALL", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => new Response(JSON.stringify({ type: "FeatureCollection", features: [], count: 0 }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const client = new HttpForecastClient({ baseUrl: "http://api.test", fetchImpl: fetchMock });
    await client.getMapRoutes({ runId: "run id", route: null, date: "2025-11-01", hour: 8 });
    await client.getDirections(1);
    await client.getStops({ route: 1, tripId: "trip/1", directionId: 0 });
    await client.getSegments({ route: 1, tripId: "trip/1", directionId: 0 });
    await client.getReferenceGeometry(1);
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "http://api.test/api/map/routes?run_id=run+id&date=2025-11-01&hour=8",
      "http://api.test/api/routes/number/1/directions",
      "http://api.test/api/routes/number/1/stops?trip_id=trip%2F1&direction_id=0",
      "http://api.test/api/routes/number/1/segments?trip_id=trip%2F1&direction_id=0",
      "http://api.test/api/routes/number/1/geometry",
    ]);
  });

  it("normalizes legacy backend directions and stops for the map overlay", async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({ route: 11, route_id: 4423, directions: [{ trip_id: 2043371, direction_id: 0 }] }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ route: { route_id: 4423 }, directions: { "0": [{ route_id: 4423, trip_id: 2043371, direction_id: 0, stop_sequence: 1, stop_id: 6152, stop_name: "Останкино", stop_lat: 55.82, stop_lon: 37.61 }] } }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const client = new HttpForecastClient({ baseUrl: "http://api.test", fetchImpl: fetchMock });
    const directions = await client.getDirections(11);
    const stops = await client.getStops({ route: 11, tripId: directions.directions[0].trip_id, directionId: directions.directions[0].direction_id });
    expect(directions).toMatchObject({ reference_version: "legacy-gtfs-4423", count: 1, directions: [{ geometry_id: "route-11-2043371-0" }] });
    expect(stops).toMatchObject({ reference_version: "legacy-gtfs-4423", count: 1, stops: [{ stop_name: "Останкино", stop_id: "6152", lat: 55.82, lon: 37.61 }] });
  });
});
