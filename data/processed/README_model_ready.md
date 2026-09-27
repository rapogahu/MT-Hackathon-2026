# Model-ready данные 2025

| Файл | Период | Строк | Колонок | Target |
|---|---|---:|---:|---|
| `model_ready_train_2025_jan_aug.csv` | Jan–Aug | 58 320 | 17 | `boardings` |
| `model_ready_validation_2025_sep_oct.csv` | Sep–Oct | 14 640 | 17 | `boardings` |
| `model_ready_train_2025_jan_oct.csv` | Jan–Oct | 72 960 | 17 | `boardings` |
| `model_ready_forecast_2025_nov_dec.csv` | Nov–Dec | 14 640 | 16 | отсутствует |

Все файлы — UTF-8 CSV с разделителем `;`. Уникальный ключ — `(route, date, hour)`; `date` записана как `YYYY-MM-DD`. Сетка содержит 10 маршрутов × все даты периода × 24 часа. Jan–Aug и Sep–Oct точно разбивают Jan–Oct с тем же порядком строк. Route 5 присутствует во всех файлах. Его исторические нули следуют из восстановления отсутствующих cells canonical grid и не доказывают фактическую нулевую нагрузку; действующая inference policy принудительно устанавливает прогноз route 5 в `0`.

**Target:** `boardings` присутствует только в трёх historical CSV. Источник — canonical `data/raw/labels/labels_day_train.csv` и `labels_day_test.csv`; отсутствующие ячейки полной сетки заполнены `0` по текущему контракту. Target validation используют только для оценки после прогноза. В forecast нет target и признаков, вычисленных из будущего target.

**`core_features` (accepted set):** `route`, `weekday`, `hour`, `route_hour`, `hour_weekend`, `is_night`. Формулы из `ml/src/feature_experiment_runner.py`: `weekday = date.weekday`, `route_hour = route * 24 + hour`, `hour_weekend = hour * 2 + int(weekday >= 5)`, `is_night = int(hour < 6)`. CSV хранит числовые коды; нужные категориальные типы задаются при model preprocessing.

**`calendar_candidate_features`:** `is_day_off`, `is_official_holiday`, `is_transferred_day_off`, `is_transferred_workday`, `is_shortened_workday`. Источник — `dataset/meta features/calendar_2025_ml.csv`, join по `date`. Для validation и forecast проверена доступность `known_from` к соответствующим forecast origins. Эти колонки не входят в accepted set.

**`weather_candidate_features`:** `climatological_temperature`, `climatological_precipitation`, `climatological_rain_probability`, `temperature_bucket`. Первые три значения получены только из frozen `dataset/meta features/moscow_weather_climatology_month_hour_2020_2024.csv` через `month(date) + hour`. Climatology построена из ERA5 2020–2024, содержит 288 уникальных month-hour ячеек без пропусков и покрывает каждую строку четырёх файлов. Она не пересчитывается по weather 2025. `temperature_bucket` вычислен из `climatological_temperature` тем же `pd.cut(..., bins=[-inf, 0, 10, 20, inf], right=False, labels=('<0', '[0,10)', '[10,20)', '>=20'))`, что и в `ml/src/weather_climatology_experiment.py`. Там это ordered pandas categorical; CSV хранит текстовые метки. При чтении для модели восстановите тип через `pd.CategoricalDtype(categories=('<0', '[0,10)', '[10,20)', '>=20'), ordered=True)` или существующий `add_temperature_bucket`.

**Исключено:** observed weather 2025 из `dataset/meta features/moscow_weather_2025_leakage_safe.csv`, любые другие будущие observed weather values и future target-derived features. Наблюдаемая погода будущего периода недоступна на forecast origin.

Команда может включать или исключать calendar и weather candidate columns в отдельных корректных temporal experiments. Наличие этих колонок в CSV не означает KEEP: Weather branch имеет статус `WEATHER_CANDIDATE_ONLY`, accepted feature registry остаётся прежним. `date` — ключ и основа для известных заранее признаков, `boardings` — только target. Текущий pilot v2 использует core + calendar candidates; weather columns в его feature set не входят.
