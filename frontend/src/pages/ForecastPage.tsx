import type { DataSource } from "../api/createDataClient";
import type { ForecastDataClient, ForecastPoint } from "../api/types";
import { ForecastChart } from "../components/ForecastChart";
import type { FixtureScenario } from "../dev/fixtureClient";
import { useForecastDashboard } from "../hooks/useForecastDashboard";

interface ForecastPageProps {
  client: ForecastDataClient;
  dataSource: DataSource;
  fixtureScenario?: FixtureScenario;
}

const categoryLabels: Record<ForecastPoint["load_category"], string> = {
  very_low: "Очень низкая",
  low: "Низкая",
  medium: "Средняя",
  high: "Высокая",
  very_high: "Очень высокая",
};

function formatDate(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Europe/Moscow",
  }).format(new Date(Date.UTC(year, month - 1, day, 12)));
}

function formatPrediction(value: number): string {
  return Math.floor(value + 0.5).toLocaleString("ru-RU");
}

function shortRun(id: string): string {
  return `${id.slice(0, 8)}…${id.slice(-4)}`;
}

export function ForecastPage({ client, dataSource, fixtureScenario }: ForecastPageProps) {
  const dashboard = useForecastDashboard(client);
  const selection = dashboard.selection;
  const point = dashboard.selectedPoint;

  return (
    <main className="app-shell">
      {dataSource === "fixtures" && (
        <div className="fixture-banner" role="status">
          <span className="fixture-pulse" aria-hidden="true" />
          <strong>Тестовые данные — не прогноз модели</strong>
          {fixtureScenario && fixtureScenario !== "default" && (
            <span>Сценарий: {fixtureScenario}</span>
          )}
        </div>
      )}

      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">M</div>
          <div>
            <p className="eyebrow">MTTECH · транспортная аналитика</p>
            <h1>Прогноз пассажиропотока</h1>
          </div>
        </div>
        {dashboard.metadata && selection && (
          <div className="run-chip" title={selection.runId}>
            <span className="run-chip-label">Выпуск</span>
            <strong>{dashboard.metadata.model_version ?? "версия не указана"}</strong>
            <span>{shortRun(selection.runId)}</span>
          </div>
        )}
      </header>

      {dashboard.notice && <div className="notice" role="status">{dashboard.notice}</div>}

      {dashboard.phase === "loading" && <LoadingState />}
      {dashboard.phase === "empty" && <EmptyState onRetry={dashboard.retry} />}
      {dashboard.phase === "error" && (
        <ErrorState message={dashboard.error ?? "Не удалось загрузить прогноз."} onRetry={dashboard.retry} />
      )}

      {dashboard.phase === "ready" && selection && dashboard.metadata && (
        <>
          <section className="context-bar" aria-label="Контекст прогноза">
            <div>
              <span>Покрытие выпуска</span>
              <strong>
                {formatDate(dashboard.metadata.forecast_start)} — {formatDate(dashboard.metadata.forecast_end)}
              </strong>
            </div>
            <div>
              <span>История до</span>
              <strong>{dashboard.metadata.training_end ? formatDate(dashboard.metadata.training_end) : "не указано"}</strong>
            </div>
            <div>
              <span>Часовой пояс</span>
              <strong>{dashboard.metadata.timezone}</strong>
            </div>
          </section>

          <section className="workspace">
            <aside className="control-panel" aria-label="Параметры прогноза">
              <div className="panel-heading">
                <span className="section-number">01</span>
                <div>
                  <p className="eyebrow">Параметры</p>
                  <h2>Срез прогноза</h2>
                </div>
              </div>

              <label className="field">
                <span>Маршрут</span>
                <select
                  aria-label="Маршрут"
                  value={selection.route}
                  onChange={(event) => dashboard.updateSelection({ route: Number(event.target.value) })}
                >
                  {dashboard.supportedRoutes.map((route) => (
                    <option key={route.route} value={route.route}>
                      Маршрут {route.route}{route.geometry_available ? "" : " · без схемы"}
                    </option>
                  ))}
                </select>
              </label>

              <div className="segmented" aria-label="Детализация">
                <button type="button" className="is-selected" aria-pressed="true">День</button>
                <button type="button" disabled title="Будет доступно на этапе FE-02">Месяц</button>
                <button type="button" disabled title="Будет доступно на этапе FE-02">Период</button>
              </div>

              <label className="field">
                <span>Дата</span>
                <input
                  aria-label="Дата"
                  type="date"
                  min={dashboard.metadata.forecast_start}
                  max={dashboard.metadata.forecast_end}
                  value={selection.date}
                  onChange={(event) => dashboard.updateSelection({ date: event.target.value })}
                />
              </label>

              <label className="field">
                <span>Час снимка</span>
                <select
                  aria-label="Час снимка"
                  value={selection.hour}
                  onChange={(event) => dashboard.updateSelection({ hour: Number(event.target.value) })}
                >
                  {Array.from({ length: 24 }, (_, hour) => (
                    <option key={hour} value={hour}>{String(hour).padStart(2, "0")}:00</option>
                  ))}
                </select>
              </label>

              <div className="scope-note">
                <span aria-hidden="true">i</span>
                Прогноз относится к маршруту целиком, а не к заполненности вагона.
              </div>
            </aside>

            <div className="dashboard-content">
              {dashboard.error && (
                <div className="inline-error" role="alert">
                  <div>
                    <strong>Данные не получены</strong>
                    <span>{dashboard.error}</span>
                  </div>
                  <button type="button" onClick={dashboard.retry}>Повторить</button>
                </div>
              )}

              <section className="kpi-grid" aria-label="Ключевые показатели">
                <KpiCard
                  index="A"
                  label="Прогноз посадок за час"
                  value={point ? formatPrediction(point.prediction) : "—"}
                  suffix="посадок"
                  context={`${formatDate(selection.date)}, ${String(selection.hour).padStart(2, "0")}:00`}
                  loading={dashboard.dataLoading}
                />
                <KpiCard
                  index="B"
                  label="Относительная загрузка"
                  value={point ? `${point.relative_load_pct}%` : "—"}
                  context="Внутри распределения маршрута"
                  loading={dashboard.dataLoading}
                />
                <KpiCard
                  index="C"
                  label="Индекс загрузки"
                  value={point ? `${point.load_index}` : "—"}
                  suffix="/ 10"
                  context={point ? categoryLabels[point.load_category] : "Категория недоступна"}
                  loading={dashboard.dataLoading}
                  accent
                />
              </section>

              {point?.normalization_degenerate && (
                <div className="warning-note" role="note">
                  Недостаточная вариативность данных; использовано условное среднее значение 50% и индекс 5.
                </div>
              )}

              <section className="chart-card">
                <div className="card-heading">
                  <div>
                    <p className="eyebrow">24 часа · маршрут {selection.route}</p>
                    <h2>Динамика посадок</h2>
                  </div>
                  <div className="chart-date">{formatDate(selection.date)}</div>
                </div>
                {dashboard.dataLoading && !dashboard.dayPoints.length ? (
                  <div className="chart-loading" role="status">Загружаем 24 часовые точки…</div>
                ) : dashboard.dayPoints.length ? (
                  <ForecastChart
                    points={dashboard.dayPoints}
                    selectedHour={selection.hour}
                    onHourSelect={(hour) => dashboard.updateSelection({ hour })}
                  />
                ) : (
                  <div className="chart-loading">Нет данных для графика</div>
                )}
              </section>

              <section className="map-placeholder" aria-label="Карта маршрута">
                <div className="map-grid" aria-hidden="true">
                  <span className="route-line route-line-a" />
                  <span className="route-line route-line-b" />
                  <span className="map-node node-a" />
                  <span className="map-node node-b" />
                  <span className="map-node node-c" />
                </div>
                <div className="map-message">
                  <span className="section-number">02</span>
                  <p className="eyebrow">Следующий этап · FE-03</p>
                  <h2>{dashboard.route?.geometry_available ? "Карта будет доступна на следующем этапе" : "Геометрия маршрута отсутствует в справочнике"}</h2>
                  <p>Прогноз, показатели и график доступны независимо от справочной схемы маршрута.</p>
                </div>
              </section>
            </div>
          </section>

          <footer className="page-footer">
            <p>Прогноз на ноябрь–декабрь 2025 построен по истории до конца октября. Фактические данные за прогнозируемый период недоступны.</p>
            <span>DAY · первый этап интерфейса</span>
          </footer>
        </>
      )}
    </main>
  );
}

function KpiCard({
  index,
  label,
  value,
  suffix,
  context,
  loading,
  accent = false,
}: {
  index: string;
  label: string;
  value: string;
  suffix?: string;
  context: string;
  loading: boolean;
  accent?: boolean;
}) {
  return (
    <article className={accent ? "kpi-card is-accent" : "kpi-card"} aria-busy={loading}>
      <div className="kpi-top"><span>{index}</span><p>{label}</p></div>
      <div className={loading ? "kpi-value is-loading" : "kpi-value"}>
        <strong>{loading ? "···" : value}</strong>
        {suffix && <span>{suffix}</span>}
      </div>
      <p className="kpi-context">{context}</p>
    </article>
  );
}

function LoadingState() {
  return (
    <section className="state-card" role="status">
      <span className="spinner" aria-hidden="true" />
      <p className="eyebrow">Подключение к данным</p>
      <h2>Загружаем доступные выпуски прогноза</h2>
    </section>
  );
}

function EmptyState({ onRetry }: { onRetry: () => void }) {
  return (
    <section className="state-card">
      <span className="state-symbol" aria-hidden="true">∅</span>
      <p className="eyebrow">Нет активного выпуска</p>
      <h2>Прогноз ещё не загружен</h2>
      <p>Как только backend опубликует модельный run, он появится здесь без подмены демо-данными.</p>
      <button type="button" onClick={onRetry}>Проверить снова</button>
    </section>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section className="state-card" role="alert">
      <span className="state-symbol" aria-hidden="true">!</span>
      <p className="eyebrow">Связь прервана</p>
      <h2>Не удалось открыть прогноз</h2>
      <p>{message}</p>
      <button type="button" onClick={onRetry}>Повторить</button>
    </section>
  );
}
