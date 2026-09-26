import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "../api/errors";
import type { ForecastDataClient } from "../api/types";
import { FIXTURE_RUN_ID, FixtureForecastClient, makeFixturePoint } from "../dev/fixtureClient";
import { ForecastPage } from "./ForecastPage";

describe("ForecastPage", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("opens the default DAY view, restores URL state and exposes 24 hour choices", async () => {
    const user = userEvent.setup();
    render(
      <ForecastPage
        client={new FixtureForecastClient({ latencyMs: 0 })}
        dataSource="fixtures"
        fixtureScenario="default"
      />,
    );

    expect(await screen.findByText("Тестовые данные — не прогноз модели")).toBeVisible();
    await waitFor(() => expect(screen.getByTestId("forecast-chart")).toHaveAttribute("aria-label", expect.stringContaining("24 точек")));
    expect(screen.getByLabelText("Маршрут")).toHaveValue("1");
    expect(screen.getByLabelText("Дата")).toHaveValue("2025-11-01");
    expect(screen.getByLabelText("Час снимка")).toHaveValue("8");
    expect(window.location.search).toContain(`run=${FIXTURE_RUN_ID}`);

    await user.selectOptions(screen.getByLabelText("Маршрут"), "17");
    await waitFor(() => expect(window.location.search).toContain("route=17"));
    expect(await screen.findByText(/Недостаточная вариативность данных/)).toBeVisible();

    const noonPrediction = makeFixturePoint(17, "2025-11-01", 12).prediction;
    await user.click(screen.getByRole("button", { name: `12:00, ${noonPrediction} посадок` }));
    await waitFor(() => expect(screen.getByLabelText("Час снимка")).toHaveValue("12"));
    expect(window.location.search).toContain("hour=12");
  });

  it("distinguishes an empty run list from zero predictions", async () => {
    render(
      <ForecastPage
        client={new FixtureForecastClient({ scenario: "empty-runs", latencyMs: 0 })}
        dataSource="fixtures"
      />,
    );

    expect(await screen.findByText("Прогноз ещё не загружен")).toBeVisible();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("shows an API failure with a retry action", async () => {
    const failingClient: ForecastDataClient = {
      getRuns: async () => { throw new ApiError(503, { code: "FORECAST_NOT_LOADED" }); },
      getRun: async () => { throw new Error("unused"); },
      getRoutes: async () => { throw new Error("unused"); },
      getDay: async () => { throw new Error("unused"); },
      getPoint: async () => { throw new Error("unused"); },
      getTimeseries: async () => { throw new Error("unused"); },
      getAggregate: async () => { throw new Error("unused"); },
      exportCsv: async () => { throw new Error("unused"); },
    };
    render(<ForecastPage client={failingClient} dataSource="api" />);

    expect(await screen.findByText("Не удалось открыть прогноз")).toBeVisible();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeEnabled();
    expect(screen.queryByText("Тестовые данные — не прогноз модели")).not.toBeInTheDocument();
  });

  it("keeps the latest filter response when an older request resolves last", async () => {
    const base = new FixtureForecastClient({ latencyMs: 0 });
    const racingClient: ForecastDataClient = {
      getRuns: (options) => base.getRuns(options),
      getRun: (runId, options) => base.getRun(runId, options),
      getRoutes: (runId, options) => base.getRoutes(runId, options),
      getDay: async (input) => {
        const value = await base.getDay(input);
        await new Promise((resolve) => window.setTimeout(resolve, input.route === 1 ? 80 : 5));
        return value;
      },
      getPoint: async (input) => {
        const value = await base.getPoint(input);
        await new Promise((resolve) => window.setTimeout(resolve, input.route === 1 ? 80 : 5));
        return value;
      },
      getTimeseries: (input, options) => base.getTimeseries(input, options),
      getAggregate: (input, options) => base.getAggregate(input, options),
      exportCsv: (input, options) => base.exportCsv(input, options),
    };
    const user = userEvent.setup();
    render(<ForecastPage client={racingClient} dataSource="fixtures" />);
    const routeSelect = await screen.findByLabelText("Маршрут");
    await user.selectOptions(routeSelect, "5");

    await waitFor(() => expect(screen.getByText("24 часа · маршрут 5")).toBeVisible());
    await new Promise((resolve) => window.setTimeout(resolve, 100));
    expect(screen.getByText("24 часа · маршрут 5")).toBeVisible();
    expect(screen.queryByText("24 часа · маршрут 1")).not.toBeInTheDocument();
  });

  it("supports MONTH, applied PERIOD drafts and ALL without invalid shared indexes", async () => {
    const user = userEvent.setup();
    render(<ForecastPage client={new FixtureForecastClient({ latencyMs: 0 })} dataSource="fixtures" />);
    await screen.findByTestId("forecast-chart");

    await user.click(screen.getByRole("button", { name: "Месяц" }));
    await waitFor(() => expect(screen.getByTestId("forecast-chart")).toHaveAttribute("aria-label", expect.stringContaining("30 точек")));
    expect(window.location.search).toContain("view=MONTH");

    await user.click(screen.getByRole("button", { name: "Период" }));
    await user.clear(screen.getByLabelText("С даты"));
    await user.type(screen.getByLabelText("С даты"), "2025-11-15");
    await user.clear(screen.getByLabelText("По дату"));
    await user.type(screen.getByLabelText("По дату"), "2025-12-05");
    expect(window.location.search).not.toContain("from=2025-11-15");
    await user.click(screen.getByRole("button", { name: "Применить период" }));
    await waitFor(() => expect(window.location.search).toContain("from=2025-11-15"));

    await user.selectOptions(screen.getByLabelText("Маршрут"), "ALL");
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(11));
    expect(screen.getAllByText("См. по маршрутам")).toHaveLength(2);
    expect(window.location.search).toContain("route=ALL");
  });
});
