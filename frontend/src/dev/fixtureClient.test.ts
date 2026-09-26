import { describe, expect, it } from "vitest";
import { FIXTURE_RUN_ID, FixtureForecastClient } from "./fixtureClient";

describe("FixtureForecastClient", () => {
  it("returns all routes and consistent DAY/POINT values", async () => {
    const client = new FixtureForecastClient({ latencyMs: 0 });
    const routes = await client.getRoutes(FIXTURE_RUN_ID);
    const day = await client.getDay({ runId: FIXTURE_RUN_ID, route: 5, date: "2025-11-01" });
    const point = await client.getPoint({ runId: FIXTURE_RUN_ID, route: 5, date: "2025-11-01", hour: 3 });

    expect(routes.routes.map((item) => item.route)).toEqual([1, 5, 7, 11, 12, 17, 25, 26, 28, 50]);
    expect(day.points).toHaveLength(24);
    expect(point.points[0]).toEqual(day.points[3]);
    expect(point.points[0].prediction).toBe(0);
  });

  it("keeps a degenerate scale explicit", async () => {
    const client = new FixtureForecastClient({ latencyMs: 0, scenario: "degenerate" });
    const point = await client.getPoint({ runId: FIXTURE_RUN_ID, route: 1, date: "2025-11-01", hour: 8 });

    expect(point.points[0]).toMatchObject({
      normalization_degenerate: true,
      relative_load_pct: 50,
      load_index: 5,
    });
  });

  it("builds exact PERIOD counts, ALL rows, aggregates and CSV from one dataset", async () => {
    const client = new FixtureForecastClient({ latencyMs: 0 });
    const single = await client.getTimeseries({ runId: FIXTURE_RUN_ID, route: 1, from: "2025-11-15", to: "2025-12-05" });
    const all = await client.getTimeseries({ runId: FIXTURE_RUN_ID, route: null, from: "2025-11-15", to: "2025-12-05" });
    const point = await client.getPoint({ runId: FIXTURE_RUN_ID, route: null, date: "2025-11-15", hour: 8 });
    const aggregate = await client.getAggregate({ runId: FIXTURE_RUN_ID, route: 1, from: "2025-11-15", to: "2025-12-05", granularity: "day" });
    const exported = await client.exportCsv({ runId: FIXTURE_RUN_ID, route: 1, from: "2025-11-15", to: "2025-12-05", hour: 8 });

    expect(single.count).toBe(504);
    expect(all.count).toBe(5040);
    expect(point.points).toHaveLength(10);
    expect(aggregate.points).toHaveLength(21);
    expect(aggregate.points.reduce((sum, item) => sum + item.prediction, 0)).toBe(single.points.reduce((sum, item) => sum + item.prediction, 0));
    expect(exported.blob.size).toBeGreaterThan(21 * 20);
    expect(exported.filename).toBe("forecast_2025-11-15_2025-12-05.csv");
  });
});
