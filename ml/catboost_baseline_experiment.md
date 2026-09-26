# CatBoostRegressor baseline — 2026-09-25

**Hypothesis:** CatBoost can improve on the fixed weekly naive profile using only calendar information available for the entire forecast horizon.

- **Data:** `data/processed/baseline_train_hourly.csv` (58,320 rows; SHA-256 `51c0eeff909392ca6070cfb8c8b2aae8fb04121bf84e7835e1db490afcfd175d`) and `data/processed/baseline_validation_hourly.csv` (14,640 rows; SHA-256 `7fce4c926d53b6b7739ed7ac01e5166d15f85d83a23685152b9e7a4ba21861a6`). Their raw-transaction construction is recorded in `ml/naive_baseline_experiment.md`.
- **Target and features:** `boardings` per `(route, date, hour)`; categorical `route`, weekday derived from `date`, and `hour`. No target lags or validation-period target information are used as features.
- **Validation:** Train on the complete January–August 2025 hourly grid. Predict the whole continuous September–October 2025 horizon before loading its `boardings`. No random split or parameter search.
- **Model:** `CatBoostRegressor(iterations=300, depth=6, learning_rate=0.1, loss_function="MAE", random_seed=42, thread_count=4)`; defaults otherwise. Clip predictions at zero and round to the nearest integer with halves up.
- **Metric:** `WAPE = sum(abs(y - prediction)) / sum(y)` over all 14,640 validation cells; `WAPE-score = max(0, 1 - WAPE)`.
- **Result:** **WAPE 0.204239; WAPE-score 0.795761.** The naive baseline on the same validation grid scored WAPE 0.209715 and WAPE-score 0.790285; this CatBoost run improves WAPE by 0.005476.
- **Reproduction:** Install `ml/requirements.txt`, then run `python ml/src/catboost_baseline.py` from the repository root. Python 3.12.6, pandas 2.2.3, NumPy 2.1.3, CatBoost 1.2.10. Code SHA-256 `d9a98e839bdf3dc367778fb2dd35ae0a2c287bce68b9feefd685d824315aabfa`; base commit `4af1e18608e088a8a6dca41a35d03c2627536fcc` (new script uncommitted at run time).
- **Conclusion:** The simple calendar model improves the temporal holdout score modestly. This is one fixed configuration, with no tuning or additional backtests.
