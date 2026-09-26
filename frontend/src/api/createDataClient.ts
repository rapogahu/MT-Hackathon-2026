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
      // Development always uses same-origin `/api`; Vite owns the backend target.
      // This prevents a stale shell-level VITE_API_BASE_URL from reviving an old port.
      baseUrl: import.meta.env.DEV ? "" : (import.meta.env.VITE_API_BASE_URL?.trim() ?? ""),
    }),
    source,
  };
}
