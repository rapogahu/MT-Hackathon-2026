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
});
