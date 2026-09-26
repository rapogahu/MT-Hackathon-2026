# ACTIVE TASK — DEV-08/09/10: стыковка frontend с FastAPI

Статус: **реализация завершена, ожидается ручной запуск frontend в API-режиме**.

## Цель

Дать корневому frontend реальный read-only HTTP-контракт FastAPI без автоматического перехода на браузерные fixtures. Сохранить существующие справочные endpoint и подготовить заменяемую границу хранения прогноза.

## Объём текущего шага

- Настраиваемый `FORECAST_CSV_PATH`; CSV читается один раз при старте, а не на каждый запрос.
- Контрактные endpoint: runs/metadata/routes, DAY, POINT, timeseries, aggregate, CSV export, map GeoJSON, directions и stops.
- Производные `relative_load`, `%`, индекс и категория рассчитываются единообразно при загрузке источника.
- Геометрия строится только из существующего Excel по `route_short_name + route_id + trip_id + direction_id`, без выдуманных линий.
- CORS и команды запуска для `frontend` в API-режиме.
- Удалить из пользовательского UI блоки «Выпуск» и «Тестовые данные — не прогноз модели».

## Не подменяет следующие задачи

- PostgreSQL, SQLAlchemy/Alembic, атомарный импорт и публикация run остаются DEV-03/04.
- Текущий CSV-репозиторий — интеграционный read-only адаптер. Его интерфейс должен позволять заменить хранение на PostgreSQL без изменения frontend DTO.
- Собственный итоговый ML forecast остаётся ML-04; тестовый submission не объявляется модельным результатом команды.

## Критерии

- [ ] Frontend с `VITE_DATA_SOURCE=api` открыт пользователем против FastAPI без fixture fallback.
- [x] DAY/POINT/timeseries/aggregate/CSV используют один контрактный run.
- [x] Map endpoint отдаёт реальную справочную GeoJSON-геометрию и индекс выбранного маршрута.
- [x] Старые routes/stops/assignments и `/health` сохранены.
- [x] Типы frontend и базовые backend/frontend проверки проходят.
- [x] README и журнал содержат точные команды локального запуска и ограничения адаптера.
