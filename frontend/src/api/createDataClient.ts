import { FixtureForecastClient, type FixtureScenario } from "../dev/fixtureClient";
import { HttpForecastClient } from "./httpClient";
import type { ForecastDataClient } from "./types";

export type DataSource = "api" | "fixtures";

interface ConfiguredClient {
  client: ForecastDataClient;
  source: DataSource;
  fixtureScenario?: FixtureScenario;
}

export function createDataClient(): ConfiguredClient {
  const source = import.meta.env.VITE_DATA_SOURCE ?? "api";

  if (source === "fixtures") {
    const scenario = import.meta.env.VITE_FIXTURE_SCENARIO ?? "default";
    return {
      client: new FixtureForecastClient({ scenario }),
      source,
      fixtureScenario: scenario,
    };
  }

  if (source !== "api") {
    throw new Error(`Unknown VITE_DATA_SOURCE: ${source}`);
  }

  return {
    client: new HttpForecastClient({
      baseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000",
    }),
    source,
  };
}
