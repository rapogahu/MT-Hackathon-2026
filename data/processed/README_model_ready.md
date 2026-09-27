# Model-ready данные 2025

- `model_ready_train_2025_jan_oct.csv`: 01.01–31.10.2025, 72 960 строк, 13 колонок.
- `model_ready_train_2025_jan_aug.csv`: 01.01–31.08.2025, 58 320 строк, 13 колонок.
- `model_ready_validation_2025_sep_oct.csv`: 01.09–31.10.2025, 14 640 строк, 13 колонок.
- `model_ready_forecast_2025_nov_dec.csv`: 01.11–31.12.2025, 14 640 строк, 12 колонок.
- Все файлы — UTF-8 CSV с разделителем `;`. Ключ: уникальный `(route, date, hour)`; `date` в формате `YYYY-MM-DD`. Сетка содержит 10 маршрутов и все 24 часа каждого дня. Jan–Aug и Sep–Oct файлы — точное разбиение Jan–Oct файла с тем же порядком и схемой колонок.

**Target:** `boardings` есть в train и validation. Источник — canonical `data/raw/labels/labels_day_train.csv` и `labels_day_test.csv`; отсутствующие ячейки полной сетки заполнены нулём по действующему контракту. Validation `boardings` использовать только для оценки после построения прогноза, не как input feature. В forecast target и производных от него признаков нет.

**`core_features` (текущий accepted set):** `route`, `weekday`, `hour`, `route_hour`, `hour_weekend`, `is_night`. Формулы взяты из `ml/src/feature_experiment_runner.py`: `weekday = date.weekday`, `route_hour = route * 24 + hour`, `hour_weekend = hour * 2 + int(weekday >= 5)`, `is_night = int(hour < 6)`. При обучении текущего LightGBM первые пять полей трактуются как категориальные; CSV хранит их числовые коды, поэтому типы категорий нужно задать при загрузке для воспроизведения pilot.

**`calendar_candidate_features` (не accepted):** `is_day_off`, `is_official_holiday`, `is_transferred_day_off`, `is_transferred_workday`, `is_shortened_workday`. Источник — `dataset/meta features/calendar_2025_ml.csv`, join по `date`. Для validation и forecast проверено: все записи с `known_from` известны к соответствующим origin 31.08.2025 и 31.10.2025; записи без `known_from` относятся к детерминированным датам или обычным выходным. Все даты покрыты.

**Исключено:** observed weather из `moscow_weather_2025_leakage_safe.csv` и любые future observed weather values. Эти данные не доступны заранее для соответствующего прогноза и не являются model features.

**Route 5:** присутствует во всех файлах. В canonical labels нет положительной истории route 5; нули в train и validation созданы восстановлением сетки и не доказывают действительную нулевую нагрузку. По действующему inference policy итоговый прогноз route 5 принудительно равен `0`; forecast файл содержит только признаки, не прогнозы.

Команда может брать весь `core_features` как текущий reference input и отдельно включать или исключать любой столбец из `calendar_candidate_features` в будущих экспериментах. `date` служит ключом и источником календарных признаков, `boardings` — только target. Изменение списка признаков требует отдельной корректной temporal validation; эти файлы сами по себе не меняют accepted set.
