"""Run inference with the frozen Pilot Model v5 artifact."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBRegressor


# Make sibling project modules importable for `python -m ml.src.predict`.
ML_SRC = Path(__file__).resolve().parent
if str(ML_SRC) not in sys.path:
    sys.path.insert(0, str(ML_SRC))

import model_selection as ms
import final_model_config as config


MODEL_PATH = config.ROOT / "ml/models/pilot_model_v5_xgboost.json"
SUBMISSION_PATH = config.ROOT / "data/end_submissions/pilot_model_v5_reproduced_submission.csv"
REFERENCE_PATH = config.ROOT / "data/end_submissions/pilot_model_v5_weighted_xgboost_submission.csv"


def main() -> None:
    forecast = pd.read_csv(
        config.FORECAST_PATH,
        sep=";",
        encoding="utf-8",
        parse_dates=["date"],
        dtype={"temperature_bucket": config.BUCKET_DTYPE},
    )
    if len(forecast) != config.FORECAST_ROWS:
        raise ValueError(f"Expected {config.FORECAST_ROWS} forecast rows, got {len(forecast)}")
    actual_period = (forecast["date"].min().strftime("%Y-%m-%d"),
                     forecast["date"].max().strftime("%Y-%m-%d"))
    if actual_period != config.FORECAST_PERIOD:
        raise ValueError(f"Expected forecast period {config.FORECAST_PERIOD}, got {actual_period}")
    if forecast.duplicated(list(config.KEYS)).any():
        raise ValueError(f"Duplicate forecast keys: {config.KEYS}")

    x_forecast = ms.make_features(forecast, config.CONFIGURATION, "XGBRegressor")
    if tuple(x_forecast.columns) != tuple(config.FEATURES):
        raise ValueError("Canonical preprocessing did not produce the frozen feature set")

    model = XGBRegressor(**config.XGBOOST_PARAMS)
    model.load_model(MODEL_PATH)
    raw_prediction = np.asarray(model.predict(x_forecast), dtype="float64")
    prediction = np.floor(np.maximum(raw_prediction, 0) + 0.5).astype("int64")
    route_5_mask = forecast["route"].to_numpy() == 5
    prediction[route_5_mask] = 0

    submission = forecast.loc[:, list(config.KEYS)].copy()
    submission["date"] = submission["date"].dt.strftime("%Y-%m-%d")
    submission["prediction"] = prediction
    submission = submission.loc[:, ["route", "date", "hour", "prediction"]]
    submission.to_csv(SUBMISSION_PATH, sep=";", index=False, encoding="utf-8")

    reference = pd.read_csv(REFERENCE_PATH, sep=";", encoding="utf-8")
    same_row_count = len(submission) == len(reference)
    compare_rows = min(len(submission), len(reference))
    keys = list(config.KEYS)
    key_matches = submission.loc[:compare_rows - 1, keys].reset_index(drop=True).equals(
        reference.loc[:compare_rows - 1, keys].reset_index(drop=True)
    ) if compare_rows else len(submission) == len(reference)
    if compare_rows:
        prediction_diff = np.abs(
            submission["prediction"].to_numpy()[:compare_rows].astype("int64")
            - reference["prediction"].to_numpy()[:compare_rows].astype("int64")
        )
        prediction_mismatches = int(np.count_nonzero(prediction_diff))
        max_abs_diff = int(prediction_diff.max())
    else:
        prediction_mismatches = 0
        max_abs_diff = 0
    prediction_mismatches += abs(len(submission) - len(reference))

    route_5_rows = int(route_5_mask.sum())
    route_5_all_zero = bool(np.all(prediction[route_5_mask] == 0))
    print(f"Forecast shape: {forecast.shape}")
    print(f"Feature shape: {x_forecast.shape}")
    print(f"Date range: {actual_period[0]}..{actual_period[1]}")
    print(f"Predictions: {len(prediction)}")
    print(f"Prediction min/max: {int(prediction.min())}/{int(prediction.max())}")
    print(f"Route 5 rows: {route_5_rows}; all zero: {route_5_all_zero}")
    print(f"Reference row count equal: {same_row_count}")
    print(f"Reference keys and order equal: {key_matches}")
    print(f"Prediction mismatches: {prediction_mismatches}")
    print(f"Max absolute prediction difference: {max_abs_diff}")
    print(f"Reproduced submission: {SUBMISSION_PATH.relative_to(config.ROOT).as_posix()}")
    if not (same_row_count and key_matches and prediction_mismatches == 0 and max_abs_diff == 0):
        print("REFERENCE COMPARISON MISMATCH: inspect diagnostics above; no automatic changes made.")


if __name__ == "__main__":
    main()
