# LightGBM baseline — 2026-09-26

**Hypothesis:** LightGBM can improve the first tree-model baseline using the same calendar information and temporal holdout.

- **Data:** `data/processed/baseline_train_hourly.csv` (58,320 rows; SHA-256 `51c0eeff909392ca6070cfb8c8b2aae8fb04121bf84e7835e1db490afcfd175d`) and `data/processed/baseline_validation_hourly.csv` (14,640 rows; SHA-256 `7fce4c926d53b6b7739ed7ac01e5166d15f85d83a23685152b9e7a4ba21861a6`). Their raw-transaction construction is recorded in `ml/naive_baseline_experiment.md`.
- **Target and features:** `boardings` per `(route, date, hour)`; categorical route, weekday derived from date, and hour. No target lags or validation-period target information are used as features.
- **Validation:** Train on January–August 2025 and predict the full continuous September–October 2025 horizon before loading its `boardings`. No random split or parameter search.
- **Model:** `LGBMRegressor(objective="regression_l1", n_estimators=300, max_depth=6, num_leaves=31, learning_rate=0.1, random_state=42, n_jobs=4, verbosity=-1)`; defaults otherwise. Clip predictions at zero and round to the nearest integer with halves up.
- **Metric:** `WAPE = sum(abs(y - prediction)) / sum(y)` over all 14,640 validation cells; `WAPE-score = max(0, 1 - WAPE)`.
- **Result:** **WAPE 0.132223; WAPE-score 0.867777.** On the same validation grid CatBoost scored WAPE 0.204239 and WAPE-score 0.795761; naive scored WAPE 0.209715 and WAPE-score 0.790285. LightGBM reduces WAPE by 0.072016 relative to CatBoost.
- **Reproduction:** Install `ml/requirements.txt`, then run `python ml/src/lightgbm_baseline.py` from the repository root. Python 3.12.6, pandas 2.2.3, NumPy 2.1.3, SciPy 1.15.2, LightGBM 4.7.0. Code SHA-256 `4c29441c2a30a381e44f9a9e7c1bf111c094bbcf65a59bc1ff567efd86b8ffe7`; base commit `074b4906202e96a5abd5e443962ca239cdde05eb` (new script uncommitted at run time).
- **Conclusion:** This single LightGBM configuration improves the shared temporal holdout substantially. Generalization to November–December is still unmeasured.
