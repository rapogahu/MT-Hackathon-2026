import { createDataClient } from "./api/createDataClient";
import { ForecastPage } from "./pages/ForecastPage";

const configuredClient = createDataClient();

export function App() {
  return (
    <ForecastPage
      client={configuredClient.client}
      dataSource={configuredClient.source}
      fixtureScenario={configuredClient.fixtureScenario}
    />
  );
}
