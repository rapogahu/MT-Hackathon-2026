# MTTECH frontend — FE-03

Интерфейс прогноза поддерживает DAY, MONTH, PERIOD, ALL, итог диапазона, CSV и справочную MapLibre-карту с выбором остановки. Модельные метрики остаются следующим этапом.

## Требования

- Node.js 22 или новее;
- npm 10 или новее.

Установка из lockfile:

```powershell
Push-Location frontend
npm ci
Pop-Location
```

## Режимы данных

Обычный запуск использует настоящий HTTP API и никогда не переключается на fixtures после ошибки:

```powershell
Push-Location frontend
npm run dev
Pop-Location
```

Dev-сервер строго слушает `http://127.0.0.1:5173` и проксирует одноимённые запросы `/api` в FastAPI на `http://127.0.0.1:8000`. Если `5173` уже занят, запуск завершается явной ошибкой вместо создания второго frontend с устаревшим окружением. Другой адрес backend задаётся через `VITE_DEV_API_TARGET`; `VITE_API_BASE_URL` применяется только в production-сборке. Клиент вызывает forecast и справочные map/geometry/directions/stops/segments endpoint из Backend §8. Терминал с Vite должен оставаться открытым до конца браузерной проверки.

Явный development-режим с синтетическими данными:

```powershell
Push-Location frontend
npm run dev:fixtures
Pop-Location
```

Детерминированные fixtures покрывают 10 маршрутов и весь диапазон 01.11–31.12.2025. Они нужны для разработки UI и не подтверждают интеграцию или качество модели.

Сценарии для ручной проверки задаются только development-переменной `VITE_FIXTURE_SCENARIO`:

- `default` — нормальный сценарий, нулевой прогноз встречается у маршрута 5;
- `empty-runs` — опубликованный выпуск отсутствует;
- `error` — ошибка получения прогноза;
- `degenerate` — вырожденная шкала 50% / индекс 5.
- `map-error` — локальная ошибка только географического блока.

Пример для PowerShell:

```powershell
$env:VITE_FIXTURE_SCENARIO = 'empty-runs'
npm run dev:fixtures
```

## Проверки и сборка

```powershell
Push-Location frontend
npm run typecheck
npm test
npm run build
npm run preview
Pop-Location
```

`npm test` выполняет один проход без watch. Production-сборка разрешена только с `VITE_DATA_SOURCE=api`; попытка собрать fixtures завершается ошибкой. Переменные и пример конфигурации перечислены в `.env.example`.

## Карта и проверка FE-03

Без `VITE_MAP_STYLE_URL` используется встроенная растровая подложка OpenStreetMap с атрибуцией. Для production рекомендуется указать собственный style URL в `.env`; ключи доступа не коммитить. Если тайлы недоступны, остаётся светлый координатный фон, а прогнозная геометрия продолжает отображаться. Fixture-схемы взяты из предоставленного XLSX для маршрутов 1/5/7/11/12. У 17/25/26/28/50 геометрия честно отсутствует.

Проверь цвет маршрута 1 для разных часов DAY, средний цвет для MONTH/PERIOD, выбор остановки, маршрут 17, ALL и сценарий `map-error`. Выбор остановки не должен менять KPI, график или состав CSV.

## Ограничения FE-03

- FastAPI read-only CSV/map endpoint реализованы; команды совместного запуска находятся в `web-forecast/README.md`.
- PostgreSQL-публикация run пока не реализована, поэтому CSV-адаптер не является production-хранилищем.
- Метрики модели пока не реализованы.
- Production требует собственный опубликованный ML-run в PostgreSQL; текущий API-адаптер предназначен для стыковки компонентов.
