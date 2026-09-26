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
});
