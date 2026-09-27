# ML model

Pilot Model v5 прогнозирует пассажиропоток по маршруту, дате и часу.

## Final model

- Solution: **Pilot Model v5**
- Model: tuned `XGBRegressor`
- Configuration: `calendar_weather`
- Train period: `2025-01-01..2025-10-31`
- Forecast period: `2025-11-01..2025-12-31`
- Features: 12
- Recency weighting: exponential, half-life 180 days (`exp(-ln(2) * age_days / 180)`)
- Postprocessing: `floor(max(raw_prediction, 0) + 0.5)`
- Route 5 predictions are forced to zero.

## Inputs

- Train: `data/processed/model_ready_train_2025_jan_oct.csv`
- Forecast: `data/processed/model_ready_forecast_2025_nov_dec.csv`

## Model artifact

- Model: `ml/models/pilot_model_v5_xgboost.json`
- Metadata: `ml/models/pilot_model_v5_metadata.json`

## Quick start

Run from the project root:

```bash
pip install -r requirements.txt
python -m ml.src.train
python -m ml.src.predict
```

## Training

`python -m ml.src.train` trains tuned `XGBRegressor` on the full Jan–Oct input with the configured 180-day recency weighting and saves the native XGBoost model artifact.

## Inference

`python -m ml.src.predict` loads the saved model, processes the Nov–Dec forecast input and writes the reproduced submission.

## Output format

Output file: `data/end_submissions/pilot_model_v5_reproduced_submission.csv`

```text
route;date;hour;prediction
```

## Reproducibility check

`predict.py` compares its output with `data/end_submissions/pilot_model_v5_weighted_xgboost_submission.csv`. The current check reports 14,640 rows, matching keys and row order, **0 prediction mismatches**, and `max_abs_diff = 0`.
