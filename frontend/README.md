# MTTECH frontend — FE-01

Первый этап интерфейса прогноза: выбор конкретного маршрута, даты и часа, DAY-график из 24 точек и три KPI. MONTH/PERIOD/ALL, CSV и настоящая карта намеренно оставлены следующим этапам.

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
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8000'
npm run dev
Pop-Location
```

Dev-сервер явно слушает `http://127.0.0.1:5173`; API по умолчанию находится на `http://127.0.0.1:8000`. Клиент вызывает операции списка выпусков, metadata, продуктового каталога, DAY и POINT из Backend §8. Терминал с Vite должен оставаться открытым до конца браузерной проверки.

Явный development-режим с синтетическими данными:

```powershell
Push-Location frontend
npm run dev:fixtures
Pop-Location
```

На экране постоянно отображается «Тестовые данные — не прогноз модели». Детерминированные fixtures покрывают 10 маршрутов и весь диапазон 01.11–31.12.2025. Они нужны для разработки UI и не подтверждают интеграцию или качество модели.

Сценарии для ручной проверки задаются только development-переменной `VITE_FIXTURE_SCENARIO`:

- `default` — нормальный сценарий, нулевой прогноз встречается у маршрута 5;
- `empty-runs` — опубликованный выпуск отсутствует;
- `error` — ошибка получения прогноза;
- `degenerate` — вырожденная шкала 50% / индекс 5.

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

## Ограничения FE-01

- Прогнозный backend пока не реализован, поэтому end-to-end проверка API не выполнена.
- Карта показана честной заглушкой следующего этапа; MapLibre пока не установлен.
- MONTH/PERIOD/ALL, CSV и метрики модели не реализованы.
- ECharts и fixture-адаптер используются только для проверки первого DAY-сценария; production требует настоящий опубликованный run.
