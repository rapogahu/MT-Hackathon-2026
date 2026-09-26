# Краткая карта текущей реализации

Проверено 26.09.2026. Подробный источник: [CURRENT_ARCHITECTURE.md](../CURRENT_ARCHITECTURE.md). Этот файл описывает код, а не будущий план.

## Работает сейчас

```text
Excel из dataset/spravochniki/
    → GTFSRepository (pandas DataFrame в памяти)
    → фабрики роутеров routes / stops / assignments
    → FastAPI /api/... → JSON

VITE_DATA_SOURCE=fixtures
    → FixtureForecastClient → React DAY / KPI / ECharts

VITE_DATA_SOURCE=api (default/production)
    → HttpForecastClient → FastAPI read-only forecast/map endpoint
```

- Точка входа: `web-forecast/app/main.py`, объект `app`.
- Репозиторий создаётся при импорте `main.py`, сразу читает шесть листов Excel. Отсутствующий/неверный файл мешает запуску.
- `main.py` передаёт один экземпляр репозитория фабрикам роутеров через аргументы; `Depends` и отдельного сервисного слоя нет.
- HTTP-обработчики синхронные. Методы репозитория фильтруют DataFrame и преобразуют значения для JSON.
- Есть `/`, `/health`, справочники маршрутов/остановок и наряды. `/docs` генерируется FastAPI.
- В корневом `frontend/` реализован FE-03: FE-02 плюс lazy MapLibre, цвет маршрута по часу или среднему индексу диапазона, выбор остановки и независимые состояния карты. Направление выбирается служебно; selector участка удалён.
- Frontend имеет общий типизированный интерфейс и два явных адаптера. Fixtures включаются только development-командой и постоянно маркируются; production допускает только HTTP API.
- HTTP-адаптер и совместимые FastAPI runs/metadata/routes/DAY/POINT/timeseries/aggregate/export/map endpoint реализованы. Backend пока использует настраиваемый read-only CSV-репозиторий; PostgreSQL-публикация ещё не реализована.

## Ключевые файлы

| Путь от корня | Назначение |
|---|---|
| `web-forecast/app/main.py` | Сборка приложения, путь к Excel, CORS, подключение роутеров |
| `web-forecast/app/api/routes.py` | Поиск по короткому номеру и по GTFS ID |
| `web-forecast/app/api/stops.py` | Список и поиск остановок |
| `web-forecast/app/api/assignments.py` | Наряды, фильтры маршрута/даты |
| `web-forecast/app/repositories/gtfs_repository.py` | Чтение/проверка Excel и методы доступа |
| `web-forecast/app/api/forecast.py` | Неподключённая 15-минутная заглушка с константами |
| `frontend/src/api/` | DTO, общий интерфейс и HTTP-клиент прогноза |
| `frontend/src/dev/fixtureClient.ts`, `referenceFixture.ts` | Числовые fixtures и справочная выборка из XLSX для FE-03 |
| `frontend/src/pages/ForecastPage.tsx` | Экран DAY, фильтры, KPI и состояния |
| `frontend/src/components/ForecastChart.tsx` | ECharts и клавиатурный выбор часа |
| `experiments.ipynb` | Отдельные эксперименты на стороннем датасете Коломны |
| `data/`, `ml/` | README и подготовленные каталоги стадий данных/ML |

## Важные ограничения

Справочник содержит номера `1,2,3,4,5,6,7,10,11,12`; конкурс — `1,5,7,11,12,17,25,26,28,50`. Номер 1 соответствует GTFS route_id 4450, а не 1. `trip_short_name` во всех координатных строках равен 0, поэтому он не идентифицирует маршрутный путь.

В Excel 489 остановок, 622 строки последовательностей с координатами, 15 нарядов за 08.02.2026 и 15 строк расписания маршрута 1. Нет полного исторического расписания или телематики для прогноза 2025 года. GeoJSON API строит справочные линии только из этих координат.

## Ещё не реализовано

PostgreSQL/Alembic и SQL-репозиторий, внешний `POST /api/predict`, реальный ML-пайплайн, атомарный импорт/публикация прогнозов, метрики, Docker Compose, полный backend test suite и benchmark. Read-only CSV/API-интеграция подготовлена, но ручной запуск frontend против неё ещё ожидается.

Вложенный `MT-Hackathon-2026/` — другой Git-проект с ранним каркасом; не использовать как runtime основного приложения. Данные в `data/raw`, `interim`, `processed` и модели исключены из Git; XLSX справочника хранится отдельно и отслеживается.

После реализации компонента обновляй этот файл и подробный CURRENT_ARCHITECTURE: что появилось, где находится и какой проверкой подтверждено.
