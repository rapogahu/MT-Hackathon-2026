# Данные проекта

В `data/` хранятся исходные данные, подготовленные таблицы для ML, результаты экспериментов и финальные submission-файлы.

- `raw/` — исходные файлы организаторов.
- `processed/` — готовые таблицы для модели. Финальный Pilot v5 обучается на `model_ready_train_2025_jan_oct.csv` и прогнозирует по `model_ready_forecast_2025_nov_dec.csv`. Схема описана в `processed/README_model_ready.md`.
- `submissions/` — сохранённые результаты отдельных экспериментов и кандидатов.
- `end_submissions/` — финальный reference `pilot_model_v5_weighted_xgboost_submission.csv` и воспроизведённый `pilot_model_v5_reproduced_submission.csv`.
- `figures/` — графики и иллюстрации анализа.
- `EDA.md` и `Features.md` — заметки об исследовании данных и признаков.
