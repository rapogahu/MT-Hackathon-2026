# ML-модель

Pilot Model v5 прогнозирует пассажиропоток по маршруту, дате и часу.

## Финальная модель

- Решение: **Pilot Model v5**
- Модель: настроенный `XGBRegressor`
- Конфигурация: `calendar_weather`
- Период обучения: `2025-01-01..2025-10-31`
- Период прогнозирования: `2025-11-01..2025-12-31`
- Количество признаков: 12
- Взвешивание по давности данных: экспоненциальное, период полураспада — 180 дней (`exp(-ln(2) * age_days / 180)`)
- Постобработка: `floor(max(raw_prediction, 0) + 0.5)`
- Для маршрута 5 все прогнозы равн 0.

## Входные данные

- Обучающая выборка: `data/processed/model_ready_train_2025_jan_oct.csv`
- Данные для прогнозирования: `data/processed/model_ready_forecast_2025_nov_dec.csv`

## Артефакты модели

- Модель: `ml/models/pilot_model_v5_xgboost.json`
- Метаданные: `ml/models/pilot_model_v5_metadata.json`

## Быстрый запуск

Запускать из корня проекта:

```bash
pip install -r requirements.txt
python -m ml.src.train
python -m ml.src.predict
```

## Обучение
Команда python -m ml.src.train обучает настроенный XGBRegressor на полной выборке за январь–октябрь с настроенным экспоненциальным взвешиванием по давности данных с периодом полураспада 180 дней и сохраняет модель в нативном формате XGBoost.

## Инференс

Команда `python -m ml.src.predict`:

1. Формирует `data/end_submissions/pilot_model_v5_reproduced_submission.csv`.
2. Сравнивает его с frozen reference `data/end_submissions/pilot_model_v5_weighted_xgboost_submission.csv`.
3. Только при полном совпадении записывает финальный runtime-прогноз в `dataset/forecast.csv`.

Backend использует `dataset/forecast.csv` как источник прогнозных данных.

## Формат файла внутри
route;date;hour;prediction

## Подробное описание эволюции архитектуры ml части
