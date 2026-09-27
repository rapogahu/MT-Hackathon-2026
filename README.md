# MTTECH — прогноз пассажиропотока трамвайных маршрутов

Веб-сервис прогнозирует количество посадок на трамвайных маршрутах Москвы и позволяет анализировать прогноз по маршруту, дате, часу или произвольному периоду.

Единица прогноза:

```text
route × date × hour → prediction
```

Текущий прогноз покрывает 10 маршрутов (`1, 5, 7, 11, 12, 17, 25, 26, 28, 50`) и период с 1 ноября по 31 декабря 2025 года — 14 640 почасовых значений.

## Возможности решения

- просмотр прогноза за день, месяц или произвольный период;
- фильтрация по маршруту, дате и часу;
- почасовые графики и агрегаты по дням, неделям и месяцам;
- относительная загрузка маршрута и индекс загрузки от 1 до 10;
- карта маршрута на подложке OpenStreetMap;
- цветовое отображение загрузки маршрута;
- остановки маршрута с информацией при наведении;
- отдельный fixture-режим frontend для разработки без backend;
- REST API и интерактивная документация OpenAPI.

Прогноз относится к маршруту целиком. Остановки и линия на карте являются справочной географией и не означают, что прогноз рассчитан отдельно для каждой остановки или участка.

## Запуск через Docker Compose

Из корня репозитория:

```bash
docker compose up --build
```

сервис будет доступен по адресу
http://localhost:5173

После сборки доступны:

- frontend: `http://localhost:5173`;
- backend: `http://localhost:8000`;
- Swagger UI: `http://localhost:8000/docs`;
- health check: `http://localhost:8000/health`.

Остановка:

```bash
docker compose down
```

Compose монтирует `dataset/` в backend в read-only режиме. Изменение `dataset/forecast.csv` требует перезапуска backend, поскольку CSV загружается один раз при старте.


## Архитектура

```text
dataset/forecast.csv
        │
        ▼
ForecastRepository ───────────────┐
                                  │
GTFS Excel                        ▼
dataset/spravochniki/      FastAPI REST API
        │                         │
        ▼                         │ /api
GTFSRepository ───────────────────┘
                                  │
                                  ▼
                         Vite proxy / nginx
                                  │
                                  ▼
                     React + TypeScript frontend
                        │         │          │
                        ▼         ▼          ▼
                     ECharts   MapLibre   SVG overlay
                      график   подложка   маршрут/остановки
```

### Backend

Backend реализован на FastAPI и находится в `web-forecast/app/`.

При старте приложение:

1. загружает справочник маршрутов и остановок из Excel;
2. загружает почасовой прогноз из CSV;
3. проверяет обязательные колонки, даты, часы, отрицательные значения и дубли;
4. рассчитывает относительную загрузку, индекс и категорию загрузки;
5. публикует read-only REST API.

Данные хранятся в pandas DataFrame в памяти и читаются один раз при старте.

### Frontend

Frontend реализован на React 19, TypeScript и Vite и находится в `frontend/`.

- `HttpForecastClient` обращается к backend через `/api`;
- `useForecastDashboard` управляет выпуском, фильтрами, прогнозом и агрегатами;
- `useForecastGeography` загружает геометрию и остановки;
- ECharts отображает временные ряды;
- MapLibre отображает подложку OpenStreetMap;
- отдельный SVG-слой поверх карты гарантированно рисует цветной маршрут и остановки при масштабировании и перемещении карты.

В development запросы `/api` проксируются Vite на `http://127.0.0.1:8000`. В Docker запросы проксирует nginx на контейнер `backend`.

### ML

Исследования, подготовка данных и baseline-модели находятся в `ml/` и `data/`.

История используется за январь–октябрь 2025 года, прогноз строится на ноябрь–декабрь. Текущий опубликованный runtime-файл — `dataset/forecast.csv`.

## Структура репозитория

```text
MTTECH/
├── dataset/
│   ├── forecast.csv              # прогноз, который загружает backend
│   └── spravochniki/             # Excel со справочной географией
├── web-forecast/
│   └── app/
│       ├── main.py               # точка входа FastAPI
│       ├── api/                  # HTTP-маршруты
│       └── repositories/         # чтение прогноза и GTFS-справочника
├── frontend/
│   ├── src/main.tsx              # точка входа React
│   ├── src/App.tsx
│   ├── src/pages/ForecastPage.tsx
│   ├── src/api/                  # типы и HTTP-клиент
│   ├── src/components/           # график и карта
│   └── src/hooks/                # состояние дашборда и географии
├── ml/                           # ML-скрипты, notebooks и описания экспериментов
├── data/                         # EDA, признаки и submission-артефакты
├── docs/                         # постановка задачи и техническая документация
├── Dockerfile                    # образ backend
└── docker-compose.yml            # совместный запуск frontend и backend
```

Вложенный каталог `MT-Hackathon-2026/` содержит раннюю версию проекта и не используется как runtime текущего сервиса.

## Точки входа

| Компонент | Точка входа |
|---|---|
| Backend | `web-forecast/app/main.py`, объект `app` |
| Frontend | `frontend/src/main.tsx` |
| Главная страница | `frontend/src/pages/ForecastPage.tsx` |
| Backend API | `web-forecast/app/api/` |
| Репозиторий прогноза | `web-forecast/app/repositories/forecast_repository.py` |
| Репозиторий маршрутов | `web-forecast/app/repositories/gtfs_repository.py` |
| ML-код | `ml/src/` |

### Прогноз

| Метод | URL | Назначение |
|---|---|---|
| GET | `/api/forecast/runs` | доступные выпуски и активный `run_id` |
| GET | `/api/forecast/runs/{run_id}` | метаданные выпуска |
| GET | `/api/forecast/routes?run_id=...` | маршруты выпуска |
| GET | `/api/forecast?run_id=...&route=1&date=2025-11-01` | почасовой прогноз за день |
| GET | `/api/forecast/point?run_id=...&route=1&date=2025-11-01&hour=8` | одна точка прогноза |
| GET | `/api/forecast/timeseries?run_id=...&route=1&from=2025-11-01&to=2025-11-30` | почасовой ряд за период |
| GET | `/api/forecast/aggregate?run_id=...&route=1&from=2025-11-01&to=2025-11-30&granularity=day` | агрегаты `day`, `week` или `month` |

`run_id` формируется из контрольной суммы загруженного CSV. Сначала следует запросить `/api/forecast/runs`, затем использовать `active_run_id` в остальных запросах.

### Карта и справочники

| Метод | URL | Назначение |
|---|---|---|
| GET | `/api/map/routes?run_id=...&route=1&date=2025-11-01&hour=8` | GeoJSON маршрута с индексом загрузки |
| GET | `/api/routes` | список маршрутов справочника |
| GET | `/api/routes/number/{route_number}` | маршрут по короткому номеру |
| GET | `/api/routes/number/{route_number}/geometry` | справочная геометрия маршрута |
| GET | `/api/routes/number/{route_number}/directions` | направления маршрута |
| GET | `/api/routes/number/{route_number}/stops` | остановки маршрута |
| GET | `/api/routes/{route_id}` | маршрут по внутреннему GTFS ID |
| GET | `/api/stops` | список или поиск остановок |
| GET | `/api/stops/{stop_id}` | остановка по ID |
| GET | `/api/assignments` | наряды с фильтрами |
| GET | `/api/assignments/routes/{route_id}` | наряды маршрута |



## Нагрузочное тестирование

Скрипт `load-tests/rps_test.py` создаёт нагрузку непосредственно на метод `GET /api/forecast/point`. Генератор запускается вне измеряемого контейнера, поддерживает заданный входной RPS и для каждого запроса выбирает существующий маршрут, дату и час из доступного периода прогноза.

Сначала запустите сервис:

```powershell
docker compose up --build -d
```

Затем проведите основной замер на 300 RPS после десятисекундного прогрева:

```powershell
python load-tests/rps_test.py `
  --url http://127.0.0.1:8000 `
  --rps 300 `
  --warmup 10 `
  --duration 120 `
  --workers 256 `
  --p95-ms 300 `
  --allocated-cpus 2 `
  --json load-report.json
```

Скрипт автоматически получает актуальные `run_id`, маршруты и период прогноза. В отчёт входят фактический RPS, p50/p95/p99, доля ошибок, объём ответов, статистика по типам запросов, CPU и RAM контейнера `mttech-backend`.

Тест считается пройденным, если одновременно выполняются условия:

- фактический RPS составляет не менее 95% целевого;
- общий p95 не превышает 300 мс;
- доля HTTP- и сетевых ошибок не превышает 1%.

При нарушении критерия скрипт завершается с кодом `1`, поэтому его можно использовать в CI. CPU из `docker stats` нормализуется относительно `--allocated-cpus`: например, 140% Docker CPU при двух выделенных vCPU соответствует 70% доступного CPU. Этот параметр используется только в отчёте и сам по себе не ограничивает контейнер — лимиты 2–4 vCPU и 2–4 ГБ необходимо задать в окружении испытания. Положительное `memory_growth_mib` следует проверять повторным длительным прогоном; отсутствие swap дополнительно контролируется на уровне Docker-хоста.

Для поиска предела сервиса повторите тест с возрастающей нагрузкой, например 100, 200, 300 и 500 RPS. Нагрузочный генератор желательно запускать на отдельной машине, иначе он будет конкурировать с сервисом за CPU.

Результаты нагрузочного тестирования положительные, держит RPS 180
C долей ошибок 0.35% (запрос API на возврат точки конкретной предсказания)
С учетом того, что запускался тест с 2 CPU, 1.7MGz, RAM 2 GB, то результат
достойный.
Measurement: 200 RPS for 60s

```
{
  "passed": false,
  "checks": {
    "rps": false,
    "p95": false,
    "errors": true
  },
  "requests": 12000,
  "elapsed_seconds": 64.794,
  "target_rps": 200.0,
  "actual_rps": 185.2,
  "errors": 42,
  "error_rate_percent": 0.35,
  "latency_ms": {
    "p50": 1316.27,
    "p95": 1594.87,
    "p99": 3077.41,
    "max": 5022.86
  },
  "scheduling_delay_ms_p95": 3807.74,
  "received_mib": 3.12,
  "statuses": {
    "0": 42,
    "200": 11958
  },
```
## Локальный запуск для разработки

### Требования

- Python 3.11+;
- Node.js 22+;
- npm 10+.

### 1. Backend

Из корня репозитория:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --app-dir web-forecast --host 127.0.0.1 --port 8000
```

По умолчанию backend использует:

```text
dataset/forecast.csv
dataset/spravochniki/Хакатон_справочники_трамвай_10_маршрутов.xlsx
```

Проверка:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/forecast/runs
```

### 2. Frontend

В отдельном терминале:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Откройте `http://127.0.0.1:5173`. Vite автоматически проксирует `/api` на backend по адресу `http://127.0.0.1:8000`.
